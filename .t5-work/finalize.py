from pathlib import Path
import json,hashlib,subprocess
p=Path('desktop_theme.py');s=p.read_text(encoding='utf-8')
names={'12243b':'navigation_background','172230':'input_background','1b4f9b':'button_hover','1d2b3c':'table_alternate','243448':'muted_background','24384c':'market_button','285f89':'market_selection','2865c4':'navigation_selection','354459':'table_grid','366487':'tab_selection','43566c':'input_border','506a82':'market_button_border','526b87':'button_border','7cb9ed':'focus_border','842e38':'danger_background','9aabbc':'disabled_text','aebed0':'hint_text','e06670':'danger_border','e0e8f3':'header_text','e3edf9':'navigation_text','e8edf4':'market_input_text','eaf0f7':'market_button_text'}
for code,name in names.items():s=s.replace('color_'+code,name)
start=s.index('COLORS = '); end=s.index('\nFONT_SIZES',start)
values=__import__('ast').literal_eval(s[start+9:end]);s=s[:start]+'COLORS = {\n'+''.join('    '+repr(k)+': '+repr(v)+',\n' for k,v in values.items())+'}'+s[end:]
s=s.replace('            Q','Q').replace('\n        \n','\n\n')
p.write_text(s,encoding='utf-8')
p=Path('desktop_market.py');s=p.read_text(encoding='utf-8').replace("}\n\n\n\n\ndef _identity", "}\n\n\ndef _identity");p.write_text(s,encoding='utf-8')
p=Path('docs/analysis/baseline/t5_theme_1366x768.json');data=json.loads(p.read_text(encoding='utf-8'))
data['reference']={'git_archive_HEAD':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'viewport':[1366,768],'platform':'offscreen','style':'Fusion','scale':1.0,'before_metrics_sha256':hashlib.sha256(Path('.t5-work/before/metrics.json').read_bytes()).hexdigest(),'after_metrics_sha256':hashlib.sha256(Path('.t5-work/after/metrics.json').read_bytes()).hexdigest(),'isolation':'Identical disposable-directory wrapper used for both captures to bypass sandbox tempfile ACL artifact.'}
p.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
