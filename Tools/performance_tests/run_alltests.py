import os, sys, shutil
import argparse, re, time

# This script runs automated performance tests for WarpX.
# It runs tests in list test_list defined below, and write
# results in file performance_log.txt in warpx/performance_tests/

# ---- User's manual ----
# Before running performance tests, make sure you have the latest version 
# of performance_log.txt
# A typical execution reads:
# python run_alltests.py --no-recompile --compiler=intel --architecture=knl --mode=run
# To add a new test item, extent the test_list with a line like
# test_list.extend([['my_input_file', n_node, n_mpi, n_omp]]*3)
# - my_input_file must be in warpx/performance_tests
# - the test will run 3 times, to have some statistics
# - the test must take <1h or it will timeout

# ---- Developer's manual ----
# This script can run in two modes:
# - 'run' mode: for each test item, a batch job is executed.
#     create folder '$SCRATCH/performance_warpx/'
#     recompile the code if option --recompile is used
#     loop over test_list and submit one batch script per item
#     Submit a batch job that executes the script in read mode
#     This last job runs once all others are completed
# - 'read' mode: Get performance data from all test items
#     create performance log file if does not exist
#     loop over test_file 
#         read initialization time and step time
#         write data into the performance log file
#         push file performance_log.txt on the repo

# Read command-line arguments
# ---------------------------

# Create parser and read arguments
parser = argparse.ArgumentParser(
    description='Run performance tests and write results in files')
parser.add_argument('--recompile', dest='recompile', action='store_true')
parser.add_argument('--no-recompile', dest='recompile', action='store_false')
parser.add_argument( '--compiler', choices=['gnu', 'intel'], default='gnu',
    help='which compiler to use')
parser.add_argument( '--architecture', choices=['cpu', 'knl'], default='cpu',
    help='which architecture to cross-compile for NERSC machines')
parser.add_argument( '--mode', choices=['run', 'read'], default='run',
    help='whether to run perftests or read their perf output. run calls read')
args = parser.parse_args()
# Dictionaries
# compiler names. Used for WarpX executable name
compiler_name = {'intel': 'intel', 'gnu': 'gcc'}
# architecture. Used for WarpX executable name
module_name = {'cpu': 'haswell', 'knl': 'mic-knl'}
# architecture. Used in batch scripts
module_Cname = {'cpu': 'haswell', 'knl': 'knl'}
# Define environment variables
cwd = os.getcwd() + '/'
res_dir_base = os.environ['SCRATCH'] + '/performance_warpx/'
bin_dir = cwd + 'Bin/'
bin_name = 'perf_tests3d.' + args.compiler + '.' + module_name[args.architecture] + '.TPROF.MPI.OMP.ex'
log_file = 'performance_log.txt'
log_dir  = cwd

# Initialize tests
# ----------------
if args.mode == 'run':
# Set default options for compilation and execution
    config_command = ''
    config_command += 'module unload darshan;' 
    config_command += 'module load craype-hugepages4M;'
    if args.architecture == 'knl':
        if args.compiler == 'intel':
            config_command += 'module unload PrgEnv-gnu;'
            config_command += 'module load PrgEnv-intel;'
        elif args.compiler == 'gnu':
            config_command += 'module unload PrgEnv-intel;'
            config_command += 'module load PrgEnv-gnu;'
        config_command += 'module unload craype-haswell;'
        config_command += 'module load craype-mic-knl;'
    elif args.architecture == 'cpu':
        if args.compiler == 'intel':
            config_command += 'module unload PrgEnv-gnu;'
            config_command += 'module load PrgEnv-intel;'
        elif args.compiler == 'gnu':
            config_command += 'module unload PrgEnv-intel;'
            config_command += 'module load PrgEnv-gnu;'
        config_command += 'module unload craype-mic-knl;'
        config_command += 'module load craype-haswell;'
    # Create main result directory if does not exist
    if not os.path.exists(res_dir_base):
        os.mkdir(res_dir_base)    

# Recompile if requested
if args.recompile == True:
    with open(cwd + 'GNUmakefile_perftest') as makefile_handler:
        makefile_text = makefile_handler.read()
    makefile_text = re.sub('\nCOMP.*', '\nCOMP=%s' %compiler_name[args.compiler], makefile_text)
    with open(cwd + 'GNUmakefile_perftest', 'w') as makefile_handler:
        makefile_handler.write( makefile_text )
    os.system(config_command + "rm -r tmp_build_dir *.mod; make -j 8 -f GNUmakefile_perftest")

# Define functions to run a test and analyse results
# --------------------------------------------------

# Run a performance test in an interactive allocation
def run_interactive(run_name, res_dir, n_node=1, n_mpi=1, n_omp=1):
    # Clean res_dir
    if os.path.exists(res_dir):
        shutil.rmtree(res_dir)
    os.makedirs(res_dir)
    # Copy files to res_dir
    shutil.copyfile(bin_dir + bin_name, res_dir + bin_name)
    shutil.copyfile(cwd  + run_name, res_dir + 'inputs')
    os.chdir(res_dir)
    if args.architecture == 'cpu':
        cflag_value = int(32/n_mpi) * 2 # Follow NERSC directives
        exec_command = 'export OMP_NUM_THREADS=' + str(n_omp) + ';' +\
                       'srun --cpu_bind=cores '     + \
                       ' -n ' + str(n_node*n_mpi) + \
                       ' -c ' + str(cflag_value)   + \
                       ' ./'  + bin_name + ' inputs > perf_output.txt'
    elif args.architecture == 'knl':
        # number of logical cores per MPI process
        cflag_value = int(68/n_mpi) * 4 # Follow NERSC directives
        exec_command = 'export OMP_NUM_THREADS=' + str(n_omp) + ';' +\
                       'srun --cpu_bind=cores '     + \
                       ' -n ' + str(n_node*n_mpi) + \
                       ' -c ' + str(cflag_value)   + \
                       ' ./'  + bin_name + ' inputs > perf_output.txt'
    os.system('chmod 700 ' + bin_name)
    os.system(config_command + exec_command)
    return 0

def run_batch(run_name, res_dir, n_node=1, n_mpi=1, n_omp=1):
    # Clean res_dir
    if os.path.exists(res_dir):
        shutil.rmtree(res_dir)
    os.makedirs(res_dir)
    # Copy files to res_dir
    shutil.copyfile(bin_dir + bin_name, res_dir + bin_name)
    shutil.copyfile(cwd + run_name, res_dir + 'inputs')
    os.chdir(res_dir)
    batch_string = ''
    batch_string += '#!/bin/bash\n'
    batch_string += '#SBATCH --job-name=' + run_name + str(n_node) + str(n_mpi) + str(n_omp) + '\n'
    batch_string += '#SBATCH --time=01:00:00\n'
    batch_string += '#SBATCH -C ' + module_Cname[args.architecture] + '\n'
    batch_string += '#SBATCH -N ' + str(n_node) + '\n'
    batch_string += '#SBATCH --partition=regular\n'
    batch_string += '#SBATCH --qos=normal\n'
    batch_string += '#SBATCH -e error.txt\n'
    batch_string += '#SBATCH --account=m2852\n'
    batch_string += 'export OMP_NUM_THREADS=' + str(n_omp) + '\n'
    if args.architecture == 'cpu':
        cflag_value = int(32/n_mpi) * 2 # Follow NERSC directives
        batch_string += 'srun --cpu_bind=cores '+ \
                    ' -n ' + str(n_node*n_mpi) + \
                    ' -c ' + str(cflag_value)   + \
                    ' ./'  + bin_name + ' inputs > perf_output.txt'
    elif args.architecture == 'knl':
        # number of logical cores per MPI process
        cflag_value = (64/n_mpi) * 4 # Follow NERSC directives
        batch_string += 'srun --cpu_bind=cores '     + \
                        ' -n ' + str(n_node*n_mpi) + \
                        ' -c ' + str(cflag_value)   + \
                        ' ./'  + bin_name + ' inputs > perf_output.txt\n'
    batch_file = 'slurm'
    f_exe = open(batch_file,'w')
    f_exe.write(batch_string)
    f_exe.close()
    os.system('chmod 700 ' + bin_name)
    os.system(config_command + 'sbatch ' + batch_file + ' >> ' + cwd + 'log_jobids_tmp.txt')
    return 0

# Read output file and return init time and 1-step time
def read_run_perf(filename):
    partition_limit = 'NCalls  Incl. Min  Incl. Avg  Incl. Max   Max %'
    with open(filename) as file_handler:
        output_text = file_handler.read()
    # Get total simulation time
    line_match_totaltime = re.search('TinyProfiler total time across processes.*', output_text)
    total_time = float(line_match_totaltime.group(0).split()[8])
    search_area = output_text.partition(partition_limit)[2]
    line_match_looptime = re.search('\nWarpX::Evolve().*', search_area)
    time_wo_initialization = float(line_match_looptime.group(0).split()[3])
    time_one_iteration = time_wo_initialization/n_steps
    time_initialization = total_time - time_wo_initialization
    return time_initialization, time_one_iteration

# Write time into logfile
def write_perf_logfile(log_file):
    day = time.strftime('%d')
    month = time.strftime('%m')
    year = time.strftime('%Y')
    log_line = ' '.join([year, month, day, run_name, args.compiler,\
                         args.architecture, str(n_node), str(n_mpi),\
                         str(n_omp), str(time_initialization),\
                         str(time_one_iteration), '\n'])
    f_log = open(log_file, 'a')
    f_log.write(log_line)
    f_log.close()
    return 0

def get_nsteps(runname):
    with open(runname) as file_handler:
        runname_text = file_handler.read()
    line_match_nsteps = re.search('\nmax_step.*', runname_text)
    nsteps = float(line_match_nsteps.group(0).split()[2])
    return nsteps

def process_analysis():
    dependencies = ''
    f_log = open(cwd + 'log_jobids_tmp.txt','r')
    for count, current_run in enumerate(test_list):
        line = f_log.readline()
        print(line)
        dependencies += line.split()[3] + ':'
    batch_string = ''
    batch_string += '#!/bin/bash\n'
    batch_string += '#SBATCH --job-name=perftests_read\n'
    batch_string += '#SBATCH --time=00:05:00\n'
    batch_string += '#SBATCH -C ' + module_Cname[args.architecture] + '\n'
    batch_string += '#SBATCH -N 1\n'
    batch_string += '#SBATCH --partition=regular\n'
    batch_string += '#SBATCH --qos=normal\n'
    batch_string += '#SBATCH -e read_error.txt\n'
    batch_string += '#SBATCH -o read_output.txt\n'
    batch_string += '#SBATCH --mail-type=end\n'
    batch_string += '#SBATCH --account=m2852\n'
    batch_string += 'python run_alltests.py --no-recompile --compiler=' + args.compiler + ' --architecture=' + args.architecture + ' --mode=read\n'
    batch_file = 'slurm_perfread'
    f_exe = open(batch_file,'w')
    f_exe.write(batch_string)
    f_exe.close()
    os.system('chmod 700 ' + batch_file)
    os.system('sbatch  --dependency afterok:' + dependencies[0:-1] + ' ' + batch_file)
    return 0
 
# Loop over the tests and return run time + details
# -------------------------------------------------

# each element of test_list contains
# [str runname, int n_node, int n_mpi, int n_omp]
test_list = []
test_list.extend([['uniform_plasma', 1, 8, 16]]*3)
test_list.extend([['uniform_plasma', 1, 4, 32]]*3)
test_list.extend([['uniform_plasma', 2, 4, 32]]*3)
n_tests   = len(test_list)
if args.mode == 'run':
    # Remove file log_jobids_tmp.txt if exists.
    # This file contains the jobid of every perf test
    # It is used to manage the analysis script dependencies
    if os.path.isfile(cwd + 'log_jobids_tmp.txt'):
        os.remove(cwd + 'log_jobids_tmp.txt')
    for count, current_run in enumerate(test_list):
        # Results folder
        print('run ' + str(current_run))
        run_name = current_run[0]
        n_node   = current_run[1]
        n_mpi    = current_run[2]
        n_omp    = current_run[3]
        n_steps  = get_nsteps(cwd + run_name)
        res_dir = res_dir_base + 'perftest' + str(count) + '/'
        # Run the simulation.
        # If you are currently in an interactive session and want to run interactive,
        # just replace run_batch with run_interactive
        run_batch(run_name, res_dir, n_node=n_node, n_mpi=n_mpi, n_omp=n_omp)
    os.chdir(cwd)
    process_analysis()

if args.mode == 'read':
    # Create log_file for performance tests if does not exist
    if not os.path.isfile(log_dir + log_file):
        log_line = '## year month day run_name compiler architecture n_node n_mpi n_omp time_initialization(s) time_one_iteration(s)\n'
        f_log = open(log_dir + log_file, 'a')
        f_log.write(log_line)
        f_log.close()
    for count, current_run in enumerate(test_list):
        # Results folder
        print('read ' + str(current_run))
        run_name = current_run[0]
        n_node   = current_run[1]
        n_mpi    = current_run[2]
        n_omp    = current_run[3]
        n_steps  = get_nsteps(cwd  + run_name)
        res_dir = res_dir_base + 'perftest' + str(count) + '/'
        # Read performance data from the output file
        time_initialization, time_one_iteration = read_run_perf(res_dir + 'perf_output.txt')
        # Write performance data to the performance log file
        write_perf_logfile(log_dir + log_file)
        
    os.system('git add ' + log_dir + log_file + ';'\
              'git commit -m "performance tests";'\
              'git push -u origin performance_tests')
