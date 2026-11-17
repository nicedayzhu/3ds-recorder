"""Double-click launcher for the direct viewer. Connection settings stay local."""
import ipaddress
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox,simpledialog

def main():
    base=Path(__file__).resolve().parent;build=base/'build';build.mkdir(exist_ok=True)
    settings=build/'preview-settings.json'
    try:previous=json.loads(settings.read_text(encoding='utf-8')).get('sender','')
    except (OSError,ValueError):previous=''
    root=tk.Tk();root.withdraw()
    while True:
        sender=simpledialog.askstring('3DS Live','3DS IPv4 address / 3DS IP 地址',initialvalue=previous,parent=root)
        if sender is None:root.destroy();return
        try:sender=str(ipaddress.IPv4Address(sender.strip()));break
        except ValueError:messagebox.showerror('3DS Live','请输入有效的 IPv4 地址',parent=root)
    settings.write_text(json.dumps({'sender':sender}),encoding='utf-8');root.destroy()
    with (build/'preview.log').open('w',encoding='utf-8') as log:
        sys.stdout=sys.stderr=log
        try:
            import receiver
            sys.argv=[str(base/'receiver.py'),'--sender',sender,'--preview','--no-output',
                      '--stats',str(build/'received.csv')]
            receiver.main()
        except Exception as error:
            import traceback
            traceback.print_exc();log.flush()
            root=tk.Tk();root.withdraw()
            messagebox.showerror('3DS Live',f'{error}\n\nLog: {build / "preview.log"}',parent=root);root.destroy()

if __name__=='__main__':main()
