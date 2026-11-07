from pathlib import Path
import argparse,subprocess,sys
from stage_guard import require_mutable_stage
require_mutable_stage()
R=Path(__file__).resolve().parent;O=R.parents[1]/'outputs'/R.name
p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--abi',required=True);p.add_argument('--label',required=True);p.add_argument('--repair',action='store_true');a=p.parse_args()
apk=O/f'ESurfingHunan-0.2.21-compat-s1-isolation-{a.abi}.apk'
def run(label,args,timeout=200):
 with (R/(label+'.log')).open('wb') as log:r=subprocess.run([sys.executable,'-B']+args,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
 print(label,r.returncode,flush=True);assert r.returncode==0,label
for i,probe in enumerate(['CompatProbe','RepairMenuProbe']):
 run(a.label+'-'+probe,[str(R/'run_device.py'),'--serial',a.serial,'--apk',str(apk),'--label',a.label+'-'+probe,'--probe',probe]+(['--install'] if i==0 else []))
run(a.label+'-ui',[str(R/'run_ui.py'),'--serial',a.serial,'--apk',str(apk),'--label',a.label+'-ui','--font','1.0'])
if a.repair:run(a.label+'-repair',[str(R/'run_device.py'),'--serial',a.serial,'--apk',str(apk),'--label',a.label+'-repair','--probe','StabilityProbe','--mode','repair','--timeout','900'],950)
