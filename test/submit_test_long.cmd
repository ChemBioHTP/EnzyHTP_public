#!/bin/bash
#SBATCH --partition=production
#SBATCH --job-name=EnzyHTP-test
#SBATCH --nodes=1
#SBATCH --tasks-per-node=1
#SBATCH --mem-per-cpu=2G
#SBATCH --time=3-00:00:00
#SBATCH --account=yang_lab_csb

source /home/shaoq1/bin/amber_env/amber-accre.sh
source ~/bin/miniconda3/bin/activate
conda activate MutaGen
export PYTHONPATH=$PYTHONPATH:~/bin/EnzyHTP

python -u -m pytest test/test_Class_PDB.py::test_get_mmpbsa_binding -s > ./test/pytest.out