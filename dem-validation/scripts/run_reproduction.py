"""Run independent checks using verified frozen inputs without upstream imports."""
import argparse
from pathlib import Path
import subprocess
import sys
from verify_source import verify_source

HERE = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--pudo-workbook', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    verify_source(args.source_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    common = ['--source-dir', str(args.source_dir.resolve()), '--output-dir', str(args.output_dir.resolve())]
    subprocess.run([sys.executable,str(HERE/'duration_data.py'),*common],check=True)
    subprocess.run([sys.executable,str(HERE/'duration_model.py'),
                    '--features-file',str(args.output_dir/'duration_features.csv'),
                    '--source-manifest',str(args.output_dir/'source_manifest.json'),
                    '--output-dir',str(args.output_dir)],check=True)
    check=[sys.executable,str(HERE/'numerical_tests.py'),*common]
    if args.pudo_workbook:check += ['--pudo-workbook',str(args.pudo_workbook.resolve())]
    subprocess.run(check,check=True)

if __name__=='__main__':main()
