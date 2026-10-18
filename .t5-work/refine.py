from pathlib import Path
import ast, pprint
p=Path('desktop_theme.py'); s=p.read_text(encoding='utf-8')
tree=ast.parse(s)
for node in reversed(tree.body):
    if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name):
        name=node.targets[0].id
        if name in ('COLORS','_QSS'):
            val=ast.literal_eval(node.value)
            replacement=name+' = '+('"""'+val+'"""' if name=='_QSS' else pprint.pformat(val,sort_dicts=False,width=88))
            lines=s.splitlines(keepends=True); lines[node.lineno-1:node.end_lineno]=[replacement+'\n']; s=''.join(lines)
s=s.replace('padding: 3px 0;', 'padding: @space_label@px 0;').replace('padding: 9px 14px;', 'padding: @space_button_vertical@px @space_button_horizontal@px;').replace('padding: 7px;', 'padding: @space_input@px;')
s=s.replace('    return result\n', "    for name, value in SPACING.items():\n        result = result.replace('@space_' + name + '@', str(value))\n    return result\n")
p.write_text(s,encoding='utf-8')
p=Path('tests/test_desktop_feedback_p0.py'); s=p.read_text(encoding='utf-8')
for widget in ('policy_form.sessions','snapshot_form','strategy_form'):
    s=s.replace("self.assertIn('#82c9ae', w."+widget+".styleSheet())", "self.assertTrue(w."+widget+".property('feedback'))\n        self.assertEqual(w."+widget+".styleSheet(), '')")
s=s.replace('colors.append(w.paper_card.label.styleSheet())', "colors.append(w.paper_card.label.property('status'))")
s=s.replace('self.assertEqual(len(set(colors)), 3)',"self.assertEqual(colors, ['success', 'danger', 'warning'])")
p.write_text(s,encoding='utf-8')
