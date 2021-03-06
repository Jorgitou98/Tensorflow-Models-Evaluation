import argparse
import subprocess
import os
import csv
import sys
sys.path.append(os.path.join(sys.path[0], '../rollouts'))
import rollout_tflite
import rollout_edge_tpu

parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument(
        '-dsp', '--depthsteppower', required=True, type=int, help='Step for increment depth step power'
)
parser.add_argument(
        '-mindp', '--mindepthpower', required=True, type=int, help='Integer indicating the min depth power'
)
parser.add_argument(
        '-maxdp', '--maxdepthpower', required=True, type=int, help='Integer indicating the max depth power'
)
parser.add_argument(
        '-psp', '--paramsteppower', required=True, type=int, help='Step for incrementing parameters power'
)
parser.add_argument(
        '-minpp', '--minparamspower', required=True, type=int, help='Integer indicating the min number of parameters power'
)

parser.add_argument(
        '-maxpp', '--maxparamspower', required=True, type=int, help='Integer indicating the max number of parameters power'
)
parser.add_argument(
        '-i', '--iters', required = True, type=int, help= 'Number of training iters to run'
)
parser.add_argument(
        '-d', '--dim', required = True, type=int, help= 'Input dimension'
)
parser.add_argument(
        '-s', '--steps', type=int, default=10000, help='Number of times to run inference'
)
args = parser.parse_args()

testFolderResult = f'test_results/depth-params/depth_pow[{args.mindepthpower}-{args.maxdepthpower}]-params_pow[{args.minparamspower}-{args.maxparamspower}]/'
if not os.path.exists(testFolderResult):
  os.mkdir(testFolderResult)

totalParamsFile = f'total_params/depth_params_pow[{args.mindepthpower}-{args.maxdepthpower}]-[{args.minparamspower}-{args.maxparamspower}].csv'
tpuResultFileName = f'{testFolderResult}tpu_results.csv'
cpuResultFileName = f'{testFolderResult}cpu_results.csv'


depthRange = [2** pow for pow in range(args.mindepthpower, args.maxdepthpower+1, args.depthsteppower)]
paramsRange = [2 ** pow for pow in range(args.minparamspower, args.maxparamspower+1, args.paramsteppower)]

# Create headers of files

with open(totalParamsFile, 'w', newline='') as outcsv:
  writer = csv.writer(outcsv)
  writer.writerow(["DEPTH", "PARAMS", "MODEL_TOTAL_PARAMS", "CONFIG"])


timeTPUout = open(tpuResultFileName, "w")
timeCPUout = open(cpuResultFileName, "w")
writerTPU = csv.writer(timeTPUout, quoting=csv.QUOTE_NONE)
writerCPU = csv.writer(timeCPUout, quoting=csv.QUOTE_NONE)
header = ["Depth"]
for params in paramsRange:
  header.append(f"{params} params")
writerTPU.writerow(header)
writerCPU.writerow(header)


# Create models and run them in TPU and CPU
for depth in depthRange:
  resultTPU = [depth]
  resultCPU = [depth]
  for params in paramsRange:

    train = f'python ../training_scripts/train_taxi_parametric.py --depth={depth} --params={params} --gpu=gpu0 --workers=1 --save-name=model_depth_params{depth}-{params} --iters={args.iters} --total-params-file={totalParamsFile}'
    process = subprocess.Popen(train.split())
    output, error = process.communicate()

    checkpointIndex = "0"*(6-len(str(args.iters)))+str(args.iters)
    export = f'python ../savers/model_saver_taxi.py ../checkpoints/ppo/model_depth_params{depth}-{params}/checkpoint_{checkpointIndex}/checkpoint-{args.iters} ../exported_models/depth-params/model{depth}-{params}/checkpoint-{args.iters}-model{depth}-{params}'
    process = subprocess.Popen(export.split())
    output, error = process.communicate()

    convert = f'python ../converters/tflite_converter_taxi.py ../exported_models/depth-params/model{depth}-{params}/checkpoint-{args.iters}-model{depth}-{params} ../exported_models/depth-params/model{depth}-{params}/checkpoint-{args.iters}-model{depth}-{params}.tflite'
    process = subprocess.Popen(convert.split())
    output, error = process.communicate()

    if not os.path.exists(f'datasets/dataset_taxi.npy'):
      create_dataset = f'python datasets/dataset_creator.py {args.dim} datasets/dataset_taxi Taxi-v3'
      process = subprocess.Popen(create_dataset.split())
      output, error = process.communicate()

    quant8b = f'python ../quantizers/quantizer8b_taxi.py ../datasets/dataset-model_taxi.npy ../exported_models/depth-params/model{depth}-{params}/checkpoint-{args.iters}-model{depth}-{params} ../exported_models/depth-params/model{depth}-{params}/checkpoint-{args.iters}-model{depth}-{params}-quant8.tflite'
    process = subprocess.Popen(quant8b.split())
    output, error = process.communicate()


    edge_tpu = f'edgetpu_compiler ../exported_models/depth-params/model{depth}-{params}/checkpoint-{args.iters}-model{depth}-{params}-quant8.tflite'
    process = subprocess.Popen(edge_tpu.split())
    output, error = process.communicate()

    move_tpu_files = f'mv checkpoint-{args.iters}-model{depth}-{params}-quant8_edgetpu.tflite ../exported_models/depth-params/model{depth}-{params}/checkpoint-{args.iters}-model{depth}-{params}-quant8_edgetpu.tflite'
    process = subprocess.Popen(move_tpu_files.split())
    output, error = process.communicate()

    clear_log = f'rm checkpoint-{args.iters}-model{depth}-{params}-quant8_edgetpu.log'
    process = subprocess.Popen(clear_log.split())
    output, error = process.communicate()

    # Inference on CPU and TPU

    modelTPU = f'../exported_models/depth-params/model{depth}-{params}/checkpoint-1-model{depth}-{params}-quant8_edgetpu.tflite'
    timeTPU = rollout_edge_tpu.main(batch = 1, num_tpus = 1, model=modelTPU, env_name="Taxi-v3", steps = args.steps)
    resultTPU.append(timeTPU)

    modelCPU = f'../exported_models/depth-params/model{depth}-{params}/checkpoint-1-model{depth}-{params}.tflite'
    timeCPU = rollout_tflite.main(batch = 1, threads = 1, model=modelCPU, env_name="Taxi-v3", steps = args.steps)
    resultCPU.append(timeCPU)

    # Remove generated files

    rm_training_results = f'rm ../training_results/ppo/model{depth}-{params}.csv ../training_results/ppo/model{depth}-{params}.json'
    process = subprocess.Popen(rm_training_results.split())
    process.communicate()

    rm_checkpoints = f'rm -r ../checkpoints/ppo/model{depth}-{params}/'
    process = subprocess.Popen(rm_checkpoints.split())
    process.communicate()

    rm_models = f'rm -r ../exported_models/depth-params/model{depth}-{params}/'
    process = subprocess.Popen(rm_models.split())
    process.communicate()

    rm_ray_results = f'rm -r ray_results/model{depth}-{params}/'
    process = subprocess.Popen(rm_ray_results.split())
    process.communicate()

  writerTPU.writerow(resultTPU)
  writerCPU.writerow(resultCPU)

timeTPUout.close()
timeCPUout.close()
