"""Tk layout/control regression check; requires a desktop session, not a 3DS."""
import json
from pathlib import Path
import tempfile
from pair_protocol import FPS_MASK,FPS_OPTIONS,RATE_OPTIONS
from preview_ui import Preview,rate_label

def main():
    with tempfile.TemporaryDirectory() as folder:
        settings=Path(folder)/'viewer-ui.json';calls=[]
        p=Preview(lambda hz,rate:calls.append((hz,rate)) or '正在应用',settings,True)
        try:
            p.root.withdraw();p.root.update_idletasks()
            height=p.root.winfo_reqheight()
            assert p.root.winfo_reqwidth()==400 and 480<height<=560
            assert p.panel.winfo_reqwidth()<=400
            assert p.hide_button.winfo_x()+p.hide_button.winfo_width()<=400
            p.show(bytes(400*480*3));photo=p.photo
            p.set_controls_visible(False);p.root.update_idletasks()
            assert p.root.winfo_reqheight()==480 and p.root.winfo_reqwidth()==400
            assert p.photo is photo and not p.panel.winfo_manager()
            assert '显示' in p.menu.entrycget(0,'label')
            p.toggle_controls();p.root.update_idletasks()
            assert p.root.winfo_reqheight()==height and p.photo is photo
            legacy=dict(sender_session=1,sender_fps=30,sender_cap=1000000,sender_max_rate=1000000,
                        sender_fps_mask=(1<<24)|(1<<30))
            p.set_telemetry(legacy,29.9,True)
            assert tuple(p.fps_box['values'])==('24','30')
            assert p.rate_box['values'][-1]==rate_label(1000000)
            r7=dict(legacy,sender_session=2,sender_max_rate=2000000,sender_fps_mask=FPS_MASK)
            p.set_telemetry(r7,30,True)
            assert tuple(p.fps_box['values'])==tuple(map(str,FPS_OPTIONS))
            assert tuple(p.rate_box['values'])==tuple(map(rate_label,RATE_OPTIONS))
            p.fps.set('15');p.rate.set(rate_label(2000000));p.apply()
            assert calls==[(15,2000000)]
            p.set_controls_visible(False)
            assert json.loads(settings.read_text())=={'controls_visible':False}
        finally:p.close()
        p=Preview(preferences_path=settings)
        try:
            p.root.withdraw();p.root.update_idletasks()
            assert not p.controls_visible and p.root.winfo_reqheight()==480
        finally:p.close()
    print(f'Preview QA: 400x{height} with controls; 400x480 hidden; R6/R7 choices, apply and persistence OK')

if __name__=='__main__':main()
