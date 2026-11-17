"""Compact direct-view controls; video geometry is always 400 x 480 pixels."""
import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk
from pair_protocol import FPS_OPTIONS,RATE_OPTIONS

PREFERENCES=Path(__file__).resolve().parent/'build/viewer-ui.json'

def rate_label(rate):return f'{rate/1000000:.2f} MB/s'

class Preview:
    def __init__(self,configure=None,preferences_path=PREFERENCES,controls_visible=None):
        self.configure=configure;self.preferences_path=preferences_path
        self.root=tk.Tk();self.root.title('3DS Live - Direct Preview')
        self.root.configure(background='black');self.root.resizable(False,False)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self._session=None;self._notice_until=0;self._notice='';self._remote={}
        style=ttk.Style(self.root);style.theme_use('clam')
        style.configure('Live.TFrame',background='black')
        style.configure('Live.TLabel',background='black',foreground='#dddddd',font=('Microsoft YaHei UI',-12))
        style.configure('Live.TCombobox',fieldbackground='#222222',background='#222222',foreground='#eeeeee',
                        arrowcolor='#cccccc',bordercolor='#444444',padding=(5,4),font=('Segoe UI',-12))
        style.map('Live.TCombobox',fieldbackground=[('readonly','#222222')],foreground=[('readonly','#eeeeee')],
                  selectbackground=[('readonly','#222222')],selectforeground=[('readonly','#eeeeee')])
        style.configure('Live.TButton',background='#222222',foreground='#dddddd',borderwidth=0,
                        padding=(7,5),font=('Microsoft YaHei UI',-12))
        style.map('Live.TButton',background=[('active','#383838'),('pressed','#444444')])
        style.configure('Apply.Live.TButton',background='#383838',foreground='white')
        style.map('Apply.Live.TButton',background=[('active','#484848'),('pressed','#555555')])
        self.root.option_add('*TCombobox*Listbox.background','#222222')
        self.root.option_add('*TCombobox*Listbox.foreground','#eeeeee')
        self.root.option_add('*TCombobox*Listbox.selectBackground','#444444')
        self.root.option_add('*TCombobox*Listbox.font',('Segoe UI',-12))
        # Fixed video frame prevents labels, status text or hiding controls from
        # changing the pixel area that OBS captures.
        self.video=tk.Frame(self.root,width=400,height=480,background='black')
        self.video.pack();self.video.pack_propagate(False)
        self.label=tk.Label(self.video,borderwidth=0,highlightthickness=0,background='black')
        self.label.pack(fill='both',expand=True)
        self.panel=ttk.Frame(self.root,style='Live.TFrame',padding=(10,6))
        self.panel.columnconfigure(3,weight=1)
        self.fps=tk.StringVar(value='30');self.rate=tk.StringVar(value=rate_label(1000000))
        ttk.Label(self.panel,text='帧率',style='Live.TLabel').grid(row=0,column=0)
        self.fps_box=ttk.Combobox(self.panel,textvariable=self.fps,values=tuple(map(str,FPS_OPTIONS)),
                                width=3,state='readonly',style='Live.TCombobox',font=('Segoe UI',-12))
        self.fps_box.grid(row=0,column=1,padx=(5,10))
        ttk.Label(self.panel,text='带宽',style='Live.TLabel').grid(row=0,column=2)
        self.rate_box=ttk.Combobox(self.panel,textvariable=self.rate,values=tuple(map(rate_label,RATE_OPTIONS)),
                                 width=10,state='readonly',style='Live.TCombobox',font=('Segoe UI',-12))
        self.rate_box.grid(row=0,column=3,padx=(5,8),sticky='ew')
        self.apply_button=ttk.Button(self.panel,text='应用',style='Apply.Live.TButton',command=self.apply,width=4)
        self.apply_button.grid(row=0,column=4,padx=(0,5))
        self.hide_button=ttk.Button(self.panel,text='隐藏 H',style='Live.TButton',command=self.toggle_controls,width=6)
        self.hide_button.grid(row=0,column=5)
        status=ttk.Frame(self.panel,style='Live.TFrame');status.grid(row=1,column=0,columnspan=6,sticky='ew',pady=(5,0))
        status.columnconfigure(0,weight=1)
        self.status=tk.StringVar(value='等待 3DS 信号');self.received=tk.StringVar(value='— FPS')
        self.status_label=ttk.Label(status,textvariable=self.status,style='Live.TLabel',width=1,anchor='w')
        self.status_label.grid(row=0,column=0,sticky='ew')
        ttk.Label(status,textvariable=self.received,style='Live.TLabel',anchor='e').grid(row=0,column=1,padx=(8,0))
        self.menu=tk.Menu(self.root,tearoff=False)
        self.menu.add_command(label='隐藏设置  H',command=self.toggle_controls)
        self.menu.add_separator()
        self.menu.add_command(label='双击画面也可显示 / 隐藏设置',state='disabled')
        self.root.bind('<KeyPress-h>',self.toggle_controls);self.root.bind('<KeyPress-H>',self.toggle_controls)
        self.root.bind('<Escape>',lambda e:self.set_controls_visible(False))
        self.root.bind('<Button-3>',self.open_menu)
        self.label.bind('<Double-Button-1>',self.toggle_controls)
        self.label.bind('<Button-1>',lambda e:self.root.focus_set())
        visible=True
        if preferences_path is not None:
            try:
                saved=json.loads(Path(preferences_path).read_text(encoding='utf-8'))
                if isinstance(saved,dict) and isinstance(saved.get('controls_visible'),bool):visible=saved['controls_visible']
            except (OSError,ValueError):pass
        self.controls_visible=not visible
        self.set_controls_visible(visible if controls_visible is None else controls_visible,persist=False)

    def open_menu(self,event):
        try:self.menu.tk_popup(event.x_root,event.y_root)
        finally:self.menu.grab_release()

    def toggle_controls(self,event=None):
        self.set_controls_visible(not self.controls_visible);return 'break'

    def set_controls_visible(self,visible,persist=True):
        self.controls_visible=bool(visible)
        if visible:self.panel.pack(fill='x')
        else:self.panel.pack_forget()
        self.menu.entryconfigure(0,label=('隐藏设置  H' if visible else '显示设置  H'))
        self.root.update_idletasks()
        # Natural height removes the complete settings area, not just its text.
        self.root.geometry(f'400x{self.root.winfo_reqheight()}')
        if persist and self.preferences_path is not None:
            try:
                path=Path(self.preferences_path);path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps({'controls_visible':self.controls_visible}),encoding='utf-8')
            except OSError:pass

    def notify(self,message,seconds=4):
        self._notice=message;self._notice_until=time.monotonic()+seconds
        self.status.set(message);self.status_label.configure(foreground='#f7c66b')

    def apply(self):
        hz=int(self.fps.get());bps=round(float(self.rate.get().split()[0])*1000000)
        message=self.configure(hz,bps) if self.configure else '等待设备连接'
        self.notify(message)

    def set_telemetry(self,remote,received_fps=0,online=False):
        self._remote=remote
        session=remote.get('sender_session',0)
        if session:
            maximum=remote.get('sender_max_rate',1000000)
            mask=remote.get('sender_fps_mask',(1<<24)|(1<<30))
            self.fps_box.configure(values=tuple(str(n) for n in FPS_OPTIONS if mask&(1<<n)))
            self.rate_box.configure(values=tuple(rate_label(n) for n in RATE_OPTIONS if (n>=400000 if maximum>1000000 else n>=700000) and n<=maximum))
            if session!=self._session:
                self.fps.set(str(remote['sender_fps']));self.rate.set(rate_label(remote['sender_cap']));self._session=session
        self.received.set(f'实收 {received_fps:.1f} FPS' if online else '— FPS')
        if time.monotonic()<self._notice_until:return
        if online and remote.get('sender_fps'):
            self.status.set(f'设备 {remote["sender_fps"]} FPS · {rate_label(remote["sender_cap"])}')
            self.status_label.configure(foreground='#94dbc0')
        else:
            self.status.set('等待 3DS 信号 · R + SELECT 开始')
            self.status_label.configure(foreground='#a7b8c7')

    def show(self,canvas):
        if self.root is None:return
        self.photo=ImageTk.PhotoImage(Image.frombytes('RGB',(400,480),bytes(canvas)),master=self.root)
        self.label.configure(image=self.photo);self.root.update()

    def poll(self):
        if self.root is not None:self.root.update()

    def close(self):
        if self.root is not None:self.root.destroy();self.root=None
