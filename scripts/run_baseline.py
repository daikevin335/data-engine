import sys 
from data_engine.baseline import run_baseline

result, counts = run_baseline(sys.argv[1])
print(result)
print(counts)