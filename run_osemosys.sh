#!/bin/bash
#PBS -N r1_osemosys_global
#PBS -l select=1:ncpus=64:mem=32gb
#PBS -l walltime=36:00:00
#PBS -o /rds/general/user/lh3417/home/osemosys_global_coc/logs/
#PBS -e /rds/general/user/lh3417/home/osemosys_global_coc/logs/

set -euo pipefail

echo "Job started on $(date)"
echo "Host: $(hostname)"
echo "PBS_O_WORKDIR: $PBS_O_WORKDIR"

cd "$PBS_O_WORKDIR"

source /rds/general/user/lh3417/home/miniforge3/etc/profile.d/conda.sh
conda activate osemosys-global
conda install -c gurobi gurobi

SCENARIO=$(python -c "
import yaml
with open('config/config.yaml') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('scenario', 'unknown'))
")
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_TAG="${SCENARIO}_${TIMESTAMP}"
echo "Scenario: $SCENARIO"
echo "Log tag:  $LOG_TAG"


which python
python --version

# ── Editable install ────────────────────────────────────────────────────────
echo "Reinstalling osemosys-global in editable mode..."
pip install -e .
echo "Editable install complete."

if [ -n "${PBS_NODEFILE:-}" ] && [ -f "$PBS_NODEFILE" ]; then
    NCPUS=$(wc -l < "$PBS_NODEFILE")
else
    NCPUS=${PBS_NCPUS:-4}
fi

conda run -n osemosys-global snakemake --unlock
conda run -n osemosys-global snakemake -j "$NCPUS"

# ── Rename logs with scenario name after job completes ───────────────────────
LOG_DIR="/rds/general/user/lh3417/home/osemosys_global/logs"

# PBS names logs as <jobname>.o<jobid> and <jobname>.e<jobid>
if [ -n "${PBS_JOBID:-}" ]; then
    JOBID="${PBS_JOBID%%.*}"   # strip queue suffix e.g. 12345.pbs → 12345
    cp "${LOG_DIR}/osemosys_global.o${JOBID}" \
       "${LOG_DIR}/${LOG_TAG}.o${JOBID}.log"  2>/dev/null || true
    cp "${LOG_DIR}/osemosys_global.e${JOBID}" \
       "${LOG_DIR}/${LOG_TAG}.e${JOBID}.err"  2>/dev/null || true
    echo "Logs copied to ${LOG_TAG}.o${JOBID}.log / .e${JOBID}.err"
fi

echo "Job finished on $(date)"
