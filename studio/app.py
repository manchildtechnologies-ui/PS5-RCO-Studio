"""Tk desktop UI. Expensive operations run in one worker, outside Tk's UI thread."""
import json
import os
from datetime import datetime
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import ImageTk
from .session import Session
from . import __version__


class Studio:
    def __init__(self, root):
        self.root = root
        self.session = None
        self.busy = False
        self.results = queue.Queue()
        self.progress_updates = queue.Queue()
        self.photo = None
        self.original_photo = None
        self.original_image = None
        self.last_project = None
        self.operation_log = []
        root.title('PS5 RCO Studio ' + __version__)
        root.geometry('1320x820')
        root.minsize(1040, 680)
        root.configure(bg='#f4f6fa')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#f4f6fa', foreground='#19243a')
        style.configure('TButton', padding=(12, 8))
        style.configure('Treeview', rowheight=29, background='white', fieldbackground='white')
        style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'), padding=7)
        style.map('Treeview', background=[('selected', '#dbeafe')], foreground=[('selected', '#102545')])
        style.configure('Title.TLabel', font=('Segoe UI', 23, 'bold'))
        style.configure('Muted.TLabel', foreground='#58657a')
        style.configure('Status.TLabel', foreground='#176647')
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        header = ttk.Frame(outer)
        header.pack(fill='x')
        ttk.Label(header, text='PS5 RCO Studio', style='Title.TLabel').pack(side='left')
        ttk.Label(header, text='OFFLINE  /  RCOF 0x110', style='Muted.TLabel').pack(side='right')
        ttk.Label(outer, text='Inspect resources, preview textures, and rebuild validated copies.',
                  style='Muted.TLabel').pack(anchor='w', pady=(2, 14))
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill='x', pady=(0, 12))
        self.open_button = ttk.Button(toolbar, text='Open RCO…', command=self.choose_open)
        self.open_button.pack(side='left')
        self.all_button = ttk.Button(toolbar, text='Export all…', command=self.choose_export_all)
        self.all_button.pack(side='left', padx=7)
        self.build_button = ttk.Button(toolbar, text='Rebuild & validate…', command=self.choose_rebuild)
        self.build_button.pack(side='left')
        self.reset_button = ttk.Button(toolbar, text='Discard staged changes', command=self.reset)
        self.reset_button.pack(side='right')
        tools = ttk.Frame(outer); tools.pack(fill='x', pady=(0, 10))
        self.project_open_button = ttk.Button(tools, text='Open extracted folder…', command=self.choose_project)
        self.project_open_button.pack(side='left')
        self.scan_button = ttk.Button(tools, text='Scan edited folder…', command=self.choose_scan)
        self.scan_button.pack(side='left', padx=5)
        self.import_button = ttk.Button(tools, text='Reimport edited folder…', command=self.choose_import)
        self.import_button.pack(side='left')
        self.batch_button = ttk.Button(tools, text='Replace multiple…', command=self.choose_batch)
        self.batch_button.pack(side='left', padx=5)
        self.validate_button = ttk.Button(tools, text='Validate', command=self.choose_validate)
        self.validate_button.pack(side='left')
        self.folder_button = ttk.Button(tools, text='Show folder', command=self.show_folder)
        self.folder_button.pack(side='left', padx=5)
        self.gallery_button = ttk.Button(tools, text='Thumbnails', command=self.show_gallery)
        self.gallery_button.pack(side='left')
        self.save_button = ttk.Button(tools, text='Save As…', command=self.choose_save_as)
        self.save_button.pack(side='right')
        self.summary = tk.StringVar(value='Open a local RCOF file to begin.')
        ttk.Label(outer, textvariable=self.summary, style='Muted.TLabel').pack(anchor='w', pady=(0, 10))
        pane = ttk.Panedwindow(outer, orient='horizontal')
        left, right = ttk.Frame(pane), ttk.Frame(pane, padding=(16, 0, 0, 0))
        pane.add(left, weight=3); pane.add(right, weight=2)
        filters = ttk.Frame(left); filters.pack(fill='x', pady=(0, 8))
        ttk.Label(filters, text='Search').pack(side='left', padx=(0, 7))
        self.search = tk.StringVar()
        self.search.trace_add('write', lambda *_: self.populate())
        search = ttk.Entry(filters, textvariable=self.search)
        search.pack(side='left', fill='x', expand=True)
        self.filter = tk.StringVar(value='All formats')
        combo = ttk.Combobox(filters, textvariable=self.filter, state='readonly', width=17,
                            values=['All formats', 'PNG', 'DDS', 'Unsupported', 'Staged'])
        combo.pack(side='right', padx=(8, 0))
        combo.bind('<<ComboboxSelected>>', lambda _: self.populate())
        self.hierarchical = tk.BooleanVar(value=False)
        ttk.Checkbutton(filters, text='Hierarchy', variable=self.hierarchical, command=self.populate).pack(side='right', padx=4)
        columns = ('id', 'name', 'offset', 'size', 'format', 'state')
        tablebox = ttk.Frame(left); tablebox.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(tablebox, columns=columns, show='headings', selectmode='browse')
        for key, title, width in zip(columns, ['ID', 'Identifier / variant', 'Offset', 'Bytes', 'Format', 'Status'],
                                     [72, 220, 96, 82, 70, 126]):
            self.tree.heading(key, text=title, command=lambda c=key: self.sort(c))
            self.tree.column(key, width=width, minwidth=65, stretch=key in ('name', 'state'))
        vertical = ttk.Scrollbar(tablebox, orient='vertical', command=self.tree.yview)
        horizontal = ttk.Scrollbar(tablebox, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky='nsew'); vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        tablebox.rowconfigure(0, weight=1); tablebox.columnconfigure(0, weight=1)
        self.tree.tag_configure('unsupported', foreground='#92632b')
        self.tree.tag_configure('staged', foreground='#176647')
        self.tree.bind('<<TreeviewSelect>>', self.select)
        self.selection_title = tk.StringVar(value='Resource preview')
        ttk.Label(right, textvariable=self.selection_title, font=('Segoe UI', 13, 'bold')).pack(anchor='w')
        self.capability = tk.StringVar(value='Select a resource to inspect its metadata.')
        ttk.Label(right, textvariable=self.capability, wraplength=430, style='Muted.TLabel').pack(anchor='w', pady=(4, 10))
        actions = ttk.Frame(right); actions.pack(fill='x', pady=(0, 10))
        self.export_button = ttk.Button(actions, text='Export selected…', command=self.choose_export_one)
        self.export_button.pack(side='left')
        self.replace_button = ttk.Button(actions, text='Stage replacement…', command=self.choose_replace)
        self.replace_button.pack(side='left', padx=(8, 0))
        self.nested_button = ttk.Button(actions, text='Nested…', command=self.choose_nested)
        self.nested_button.pack(side='left', padx=(8, 0))
        self.tabs = ttk.Notebook(right); self.tabs.pack(fill='both', expand=True)
        preview_frame, metadata_frame, validation_frame = ttk.Frame(self.tabs), ttk.Frame(self.tabs), ttk.Frame(self.tabs)
        self.tabs.add(preview_frame, text='Preview'); self.tabs.add(metadata_frame, text='Metadata')
        self.tabs.add(validation_frame, text='Validation')
        self.preview_canvas = tk.Canvas(preview_frame, bg='#e8edf4', highlightthickness=0)
        self.preview_canvas.pack(fill='both', expand=True)
        self.preview_canvas.bind('<Configure>', lambda _: self.draw_preview())
        self.preview_image = None
        self.metadata = self.text_box(metadata_frame)
        self.validation = self.text_box(validation_frame)
        self.nested_frame = ttk.Frame(self.tabs); self.tabs.add(self.nested_frame, text='Nested')
        nested_list = ttk.Frame(self.nested_frame); nested_list.pack(fill='both', expand=True)
        self.nested_tree = ttk.Treeview(nested_list, columns=('id', 'text'), show='headings', height=9)
        self.nested_tree.heading('id', text='String identifier'); self.nested_tree.heading('text', text='Text / value')
        self.nested_tree.column('id', width=170); self.nested_tree.column('text', width=240)
        nested_scroll = ttk.Scrollbar(nested_list, command=self.nested_tree.yview)
        self.nested_tree.configure(yscrollcommand=nested_scroll.set)
        nested_scroll.pack(side='right', fill='y'); self.nested_tree.pack(fill='both', expand=True)
        self.nested_tree.bind('<<TreeviewSelect>>', self.nested_selected)
        self.nested_text = tk.Text(self.nested_frame, height=5, wrap='word'); self.nested_text.pack(fill='x')
        row = ttk.Frame(self.nested_frame); row.pack(fill='x')
        self.nested_stage = ttk.Button(row, text='Stage string edit', command=self.stage_nested)
        self.nested_stage.pack(side='left')
        self.nested_export = ttk.Button(row, text='Extract nested…', command=self.extract_nested)
        self.nested_export.pack(side='left', padx=5)
        self.nested_info = tk.StringVar(value='Nested RCSF: equal UTF-16 byte lengths only. XML: inspect/export only.')
        ttk.Label(self.nested_frame, textvariable=self.nested_info, wraplength=430).pack(fill='x', pady=5)
        self.log_frame = ttk.Frame(self.tabs); self.tabs.add(self.log_frame, text='Logs / errors')
        ttk.Button(self.log_frame, text='Save operation log…', command=self.save_log).pack(anchor='w', pady=4)
        self.logs = self.text_box(self.log_frame)
        self.nested_resource = None; self.nested_report = None
        self.status = tk.StringVar(value='Ready. Originals remain untouched; outputs use a separate folder.')
        # Reserve the footer before the expandable browser; otherwise notebook
        # requested height can push progress/error messages below the window.
        statusbar = ttk.Frame(outer); statusbar.pack(side='bottom', fill='x', pady=(8, 0))
        ttk.Label(statusbar, textvariable=self.status, style='Status.TLabel', wraplength=1220).pack(anchor='w', pady=(2, 4))
        self.progress = ttk.Progressbar(statusbar, mode='indeterminate')
        self.progress.pack(fill='x')
        ttk.Label(statusbar, text='PNG supports verified size changes by relocation. Dimensions and encoding must match. DDS requires its original stored size. '
                  'RCSF string edits preserve byte lengths. Console acceptance is untested.',
                  style='Muted.TLabel', wraplength=1240).pack(anchor='w', pady=(8, 0))
        pane.pack(fill='both', expand=True)
        self.update_actions()
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = root.after(60, self.poll)
        root.bind('<Destroy>', self.destroyed, add='+')
        menu = tk.Menu(root); file_menu = tk.Menu(menu, tearoff=False)
        for title, command in [('Open RCO…', self.choose_open), ('Open extracted folder…', self.choose_project),
                ('Extract selected…', self.choose_export_one), ('Extract all / editable project…', self.choose_export_all),
                ('Show extracted folder', self.show_folder), ('Reimport edited folder…', self.choose_import),
                ('Repack…', self.choose_rebuild), ('Validate', self.choose_validate), ('Save As…', self.choose_save_as)]:
            file_menu.add_command(label=title, command=command)
        menu.add_cascade(label='File', menu=file_menu); root.configure(menu=menu)

    def text_box(self, frame):
        box = tk.Text(frame, wrap='word', font=('Consolas', 10), bg='white', relief='flat', padx=10, pady=10)
        scroll = ttk.Scrollbar(frame, command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); box.pack(fill='both', expand=True)
        box.configure(state='disabled')
        return box

    def set_text(self, box, text):
        box.configure(state='normal'); box.delete('1.0', 'end'); box.insert('1.0', text); box.configure(state='disabled')

    def update_actions(self):
        ready = self.session is not None and not self.busy
        writable = ready and not self.session.container.read_only
        selected = self.tree.selection()
        item = self.session.resource(selected[0]) if ready and selected and selected[0] in self.session.resources else None
        self.all_button.configure(state='normal' if ready else 'disabled')
        self.build_button.configure(state='normal' if writable else 'disabled')
        self.open_button.configure(state='disabled' if self.busy else 'normal')
        self.reset_button.configure(state='normal' if ready and self.session.pending else 'disabled')
        self.export_button.configure(state='normal' if item else 'disabled')
        can_edit = item and item['replacement_supported'] and (not item.get('shared_with') or self.session.relocation_reason(item['id']) is None)
        self.replace_button.configure(state='normal' if writable and can_edit else 'disabled')
        for button in (self.scan_button, self.gallery_button):
            button.configure(state='normal' if ready else 'disabled')
        for button in (self.import_button, self.batch_button, self.validate_button, self.save_button):
            button.configure(state='normal' if writable else 'disabled')
        self.project_open_button.configure(state='disabled' if self.busy else 'normal')
        self.folder_button.configure(state='normal' if self.last_project and not self.busy else 'disabled')
        self.nested_button.configure(state='normal' if item and item['kind'] in ('rcsf', 'xml') else 'disabled')
        self.nested_stage.configure(state='normal' if writable and self.nested_report and self.nested_resource in self.session.resources and
                                    self.session.resource(self.nested_resource)['kind'] == 'rcsf' and
                                    not self.session.resource(self.nested_resource).get('shared_with') else 'disabled')
        self.nested_export.configure(state='normal' if ready and self.nested_resource in self.session.resources else 'disabled')

    def submit(self, label, work, done):
        if self.busy: return
        self.busy = True; self.status.set(label); self.progress.start(12); self.update_actions()
        self.log(label)
        def execute():
            try: self.results.put((done, work(), None))
            except Exception as exc:
                import traceback
                self.results.put((done, None, (exc, traceback.format_exc())))
        threading.Thread(target=execute, daemon=False).start()

    def poll(self):
        latest = None
        while not self.progress_updates.empty(): latest = self.progress_updates.get_nowait()
        if latest: self.status.set(f'Checking extracted resources: {latest[0]:,} / {latest[1]:,}')
        try:
            done, value, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False; self.progress.stop()
            if error:
                exc, details = error
                self.status.set('Operation failed: ' + str(exc))
                self.log('FAIL: ' + str(exc) + '\n' + details)
                if self.session and self.session.last_report:
                    self.set_text(self.validation, json.dumps(self.session.last_report, indent=2))
                messagebox.showerror('Operation failed', str(exc) + '\n\nSee Logs / errors for details.', parent=self.root)
            else:
                done(value)
                self.log('PASS: operation completed')
            self.update_actions()
        self.poll_id = self.root.after(60, self.poll)

    def destroyed(self, event):
        if event.widget == self.root:
            self.root.after_cancel(self.poll_id)

    def choose_open(self):
        if self.session and self.session.pending and not messagebox.askyesno(
                'Discard staged changes?', 'Open another file and discard the staged replacements?', parent=self.root): return
        path = filedialog.askopenfilename(parent=self.root, title='Open RCOF', filetypes=[('RCO containers', '*.rco'), ('All files', '*.*')])
        if path: self.open_path(path)

    def open_path(self, path):
        self.submit('Reading and validating resource tables…', lambda: Session(path), self.loaded)

    def loaded(self, session):
        self.session = session; self.search.set(''); self.filter.set('All formats')
        self.populate(); self.refresh_summary()
        self.preview_image = None; self.photo = None; self.draw_preview()
        self.selection_title.set('Resource preview'); self.capability.set('Select a resource to inspect its metadata.')
        self.set_text(self.metadata, ''); self.set_text(self.validation, '')
        self.status.set('Opened ' + str(session.source))
        if session.container.read_only:
            self.status.set('READ-ONLY: unsupported contained/partial file ranges. Inspection and extraction remain available; rebuilding is blocked.')
            self.log(json.dumps(dict(range_issues=session.container.range_issues), indent=2))
        elif session.container.alias_groups:
            self.status.set('Opened with ' + str(len(session.container.alias_groups)) + ' exact shared ranges. Unedited sharing is preserved; verified image edits use copy-on-write.')
        self.nested_report = None; self.nested_resource = None
        self.nested_tree.delete(*self.nested_tree.get_children())

    def refresh_summary(self):
        c = self.session.current_container
        supported = sum(x['replacement_supported'] and (not x.get('shared_with') or self.session.relocation_reason(x['id']) is None)
                        for x in c.resources)
        self.summary.set(f'{self.session.source.name}   •   {len(c.resources):,} resources   •   '
                         f'{supported:,} image replacements supported   •   {len(c.resources)-supported:,} export-only   •   '
                         f'{len(self.session.pending)} staged   •   {len(c.alias_groups)} shared groups' +
                         ('   •   READ-ONLY' if c.read_only else ''))

    def populate(self):
        if not self.session or self.busy: return
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        query, kind = self.search.get().lower(), self.filter.get()
        self.tree.configure(show='tree headings' if self.hierarchical.get() else 'headings')
        self.tree.column('#0', width=150)
        nodes = self.session._nodes
        def parent_for(offset):
            key = 'node:' + str(offset)
            if self.tree.exists(key): return key
            node = nodes[offset]
            parent = '' if node['parent'] == 0xFFFFFFFF else parent_for(node['parent'])
            self.tree.insert(parent, 'end', iid=key, text=node['name'] or node['tag'], open=True,
                             values=('', node['name'] or node['tag'], f'0x{node["absolute_offset"]:08X}', '', node['tag'], 'Structure'))
            return key
        for item in self.session.current_container.resources:
            ident = item['id']; staged = ident in self.session.pending
            if query and query not in f'{ident} {item["name"]} {item["attribute"]} {item["kind"]}'.lower(): continue
            if kind in ('PNG', 'DDS') and item['kind'] != kind.lower(): continue
            if kind == 'Unsupported' and item['replacement_supported']: continue
            if kind == 'Staged' and not staged: continue
            editable = item['replacement_supported'] and (not item.get('shared_with') or self.session.relocation_reason(ident) is None)
            state = 'Staged' if staged else ('Shared / ' if item.get('shared_with') else '') + ('Replace supported' if editable else 'Export only')
            parent = parent_for(item['node_offset']) if self.hierarchical.get() else ''
            self.tree.insert(parent, 'end', iid=ident, text=item['attribute'], values=(ident, f'{item["name"] or item["tag"]} / {item["attribute"]}',
                             f'0x{item["offset"]:08X}', f'{item["size"]:,}', item['kind'].upper(), state),
                             tags=('staged' if staged else '' if item['replacement_supported'] else 'unsupported',))
        if selected and self.tree.exists(selected[0]): self.tree.selection_set(selected[0])
        else:
            self.preview_image = None; self.photo = None; self.draw_preview()
            self.selection_title.set('Resource preview')
            self.capability.set('Select a resource to inspect its metadata.')
            self.set_text(self.metadata, '')
        self.update_actions()

    def sort(self, column):
        if self.busy: return
        if self.hierarchical.get():
            self.status.set('Hierarchy preserves stored node order. Disable Hierarchy to sort resource columns.'); return
        keys = {'offset': 'offset', 'size': 'size', 'format': 'kind', 'name': 'name', 'id': 'id'}
        reverse = getattr(self, '_sort', None) == (column, False)
        self._sort = (column, reverse)
        def key(ident):
            item = self.session.resource(ident)
            return (ident in self.session.pending, item['replacement_supported']) if column == 'state' else item[keys[column]] or ''
        for index, ident in enumerate(sorted(self.tree.get_children(), key=key, reverse=reverse)):
            self.tree.move(ident, '', index)

    def select(self, _event=None):
        if self.busy or not self.session or not self.tree.selection(): return
        ident = self.tree.selection()[0]
        if ident not in self.session.resources:
            self.set_text(self.metadata, json.dumps(self.session._nodes[int(ident.split(':')[1])], indent=2))
            self.preview_image = None; self.original_image = None; self.photo = None
            self.draw_preview(); self.update_actions(); return
        item = self.session.resource(ident)
        self.selection_title.set(item['name'] or item['id'])
        reason = self.session.relocation_reason(ident)
        shared = item.get('shared_with', [])
        supported_text = ('PNG relocation supported: larger or smaller stored files; same dimensions and encoding.' if item['kind'] == 'png' else
                          'Shared DDS: fixed-size copy-on-write supported; identical header required.') if reason is None else 'Fixed-size replacement only. ' + reason
        if shared:
            supported_text = ('Shared with ' + ', '.join(shared) + '. ' +
                              ('Image edits use independent copy-on-write. ' if reason is None else 'Raw sharing is preserved; unsupported edits are blocked. ') + supported_text)
        self.capability.set(f'{item["kind"].upper()}  /  {item["size"]:,} bytes  /  {item["attribute"]}\n' +
                            (supported_text if item['replacement_supported'] else
                             'Export only for raw replacement: ' + str(item['unsupported_reason']) +
                             ('; shared with ' + ', '.join(shared) if shared else '') +
                             ('; Nested supports validated equal-byte RCSF string edits.' if item['kind'] == 'rcsf' and not shared else '')))
        node = next(n for n in self.session.current_container.nodes if n['offset'] == item['node_offset'])
        self.set_text(self.metadata, json.dumps(dict(resource=item, hierarchy=self.session.hierarchy(ident), node=node, relocation_supported=reason is None,
                                                   relocation_restriction=reason), indent=2))
        self.preview_image = None; self.original_image = None; self.photo = None
        if item['kind'] in ('png', 'dds') and item['image']:
            try:
                self.preview_image = self.session.preview(ident)
                self.original_image = self.session.preview(ident, original=True) if ident in self.session.pending else None
                self.photo = ImageTk.PhotoImage(self.preview_image, master=self.root)
            except Exception as exc:
                self.capability.set('Preview unavailable: ' + str(exc))
        self.draw_preview(); self.update_actions()

    def draw_preview(self):
        self.preview_canvas.delete('all')
        width, height = self.preview_canvas.winfo_width(), self.preview_canvas.winfo_height()
        if self.preview_image:
            fitted = self.preview_image.copy()
            fitted.thumbnail((max(1, width // 2 - 24 if self.original_image else width - 24), max(1, height - 48)))
            self.photo = ImageTk.PhotoImage(fitted, master=self.root)
            self.preview_canvas.create_image(width * 3 // 4 if self.original_image else width // 2, height // 2, image=self.photo)
            if self.original_image:
                old = self.original_image.copy(); old.thumbnail((max(1, width // 2 - 24), max(1, height - 48)))
                self.original_photo = ImageTk.PhotoImage(old, master=self.root)
                self.preview_canvas.create_image(width // 4, height // 2, image=self.original_photo)
                self.preview_canvas.create_text(width // 4, 20, text='Original', fill='#58657a')
                self.preview_canvas.create_text(width * 3 // 4, 20, text='Staged replacement', fill='#176647')
        else:
            self.preview_canvas.create_text(max(100, width // 2), max(80, height // 2),
                text='No image preview\nSelect a supported PNG or DDS resource.', fill='#58657a', justify='center', width=320)

    def output_folder(self):
        return filedialog.askdirectory(parent=self.root, title='Choose a separate output folder', mustexist=False)

    def choose_export_one(self):
        selected = self.tree.selection()
        if not selected or self.busy: return
        folder = self.output_folder()
        if folder: self.submit('Exporting selected resource…', lambda: self.session.export_one(selected[0], folder),
                               lambda p: self.status.set('Exported ' + str(p)))

    def choose_export_all(self):
        if not self.session or self.busy: return
        folder = self.output_folder()
        if folder: self.submit('Extracting editable project with recovery baseline…', lambda: self.session.export_project(folder), self.project_exported)

    def choose_replace(self):
        selected = self.tree.selection()
        if not selected or self.busy: return
        if selected[0] not in self.session.resources: return
        item = self.session.resource(selected[0])
        if not item['replacement_supported']: return
        rule = ('PNG size changes supported' if item['kind'] == 'png' else 'Shared DDS copy-on-write; original size/header required') if self.session.relocation_reason(selected[0]) is None else f'original size required: {self.session.original_resources[selected[0]]["size"]:,} bytes'
        path = filedialog.askopenfilename(parent=self.root, title=f'Replace {selected[0]} — {rule}',
                                         filetypes=[('Image', '*.' + item['kind']), ('All files', '*.*')])
        if path: self.submit('Validating replacement image…', lambda: self.session.stage(selected[0], path), self.staged)

    def staged(self, report):
        self.refresh_summary(); self.populate(); self.select()
        self.status.set(f'{report["resource_id"]} staged ({report["mode"]}, {report["size"]:,} bytes). Original unchanged. Rebuild to save a validated copy.')

    def reset(self):
        if self.busy or not self.session: return
        self.session.reset(); self.refresh_summary(); self.populate(); self.select()
        self.status.set('Staged replacements discarded.')

    def choose_rebuild(self):
        if not self.session or self.busy: return
        folder = self.output_folder()
        if folder: self.submit('Reconstructing and validating output…', lambda: self.session.rebuild(folder), self.built)

    def choose_save_as(self):
        if not self.session or self.busy: return
        path = filedialog.asksaveasfilename(parent=self.root, title='Save a new validated RCO copy', defaultextension='.rco',
                                          initialfile=self.session.source.stem + '.rebuilt.rco', filetypes=[('RCOF containers', '*.rco')])
        if path: self.submit('Saving and validating output copy…', lambda: self.session.save_as(path), self.built)

    def built(self, report):
        self.set_text(self.validation, json.dumps(report, indent=2))
        self.tabs.select(2)
        self.status.set('PASS — ' + ('byte-identical reconstruction' if report['byte_identical'] else 'validated PNG relocation' if
                                   report['mode'] == 'png-relocation' else 'validated shared copy-on-write' if report['mode'] == 'shared-copy-on-write' else 'validated fixed-size replacement') +
                        '. Saved: ' + report['output'])

    def log(self, text):
        self.operation_log.append(datetime.now().strftime('%H:%M:%S') + '  ' + text)
        self.operation_log = self.operation_log[-300:]
        self.set_text(self.logs, '\n\n'.join(self.operation_log))

    def save_log(self):
        if self.busy: return
        path = filedialog.asksaveasfilename(parent=self.root, title='Save log to a new text file', defaultextension='.txt')
        if not path: return
        from Rcomage import rcof
        try:
            rcof.write_new(path, ('\n\n'.join(self.operation_log) + '\n').encode('utf-8'))
            self.status.set('Operation log saved: ' + path)
        except OSError as exc: messagebox.showerror('Cannot save log', str(exc), parent=self.root)

    def project_exported(self, report):
        self.last_project = report['directory']
        self.status.set('Editable project extracted: ' + self.last_project)
        self.log(json.dumps(report, indent=2))

    def choose_project(self):
        if self.busy: return
        folder = filedialog.askdirectory(parent=self.root, title='Open extracted project folder')
        if not folder: return
        if self.session and self.session.pending and not messagebox.askyesno('Discard changes?', 'Open project and discard current staged edits?', parent=self.root): return
        def loaded(value):
            self.loaded(value); self.last_project = folder
            self.status.set('Project opened. Scan or reimport its edited files before repacking.')
        self.submit('Opening extracted recovery baseline…', lambda: Session.open_project(folder), loaded)

    def edited_folder(self):
        return filedialog.askdirectory(parent=self.root, title='Choose extracted project to check / reimport',
                                       initialdir=self.last_project or str(self.session.source.parent))

    def choose_scan(self):
        if not self.session or self.busy: return
        folder = self.edited_folder()
        if folder:
            self.last_project = folder
            self.submit('Scanning edited project…', lambda: self.session.scan_project(folder, self.report_progress), self.scanned)

    def report_progress(self, current, total): self.progress_updates.put((current, total))

    def scanned(self, report):
        self.set_text(self.validation, json.dumps(report, indent=2)); self.tabs.select(2)
        self.status.set(f'{report["status"]}: {len(report["modified"]):,} modified, {len(report["unchanged"]):,} unchanged, '
                        f'{len(report["missing"])} missing, {len(report["additional"])} additional. No changes staged by scan.')

    def choose_import(self):
        if not self.session or self.busy: return
        folder = self.edited_folder()
        if folder:
            self.last_project = folder
            self.submit('Validating and reimporting edited resources…', lambda: self.session.import_project(folder, self.report_progress), self.imported)

    def imported(self, report):
        self.refresh_summary(); self.populate(); self.select()
        self.set_text(self.validation, json.dumps(report, indent=2)); self.tabs.select(2)
        self.status.set(f'Reimport complete: {report["staged"]} resources staged. Repack to save a validated copy.')

    def choose_batch(self):
        if not self.session or self.busy: return
        paths = filedialog.askopenfilenames(parent=self.root, title='Choose replacements named like extracted resource files',
                                            filetypes=[('Images', '*.png *.dds'), ('All files', '*.*')])
        if not paths: return
        try:
            names = {Path(x['file']).name: x['id'] for x in self.session.container.resources}
            mapped = {}
            for path in paths:
                name = Path(path).name
                if name not in names: raise ValueError('Unmatched replacement name: ' + name + '. Use exact extracted filenames.')
                if names[name] in mapped: raise ValueError('Duplicate replacement: ' + name)
                mapped[names[name]] = path
            self.submit('Validating batch replacements atomically…', lambda: self.session.stage_multiple(mapped), self.imported)
        except ValueError as exc:
            self.log('FAIL: ' + str(exc)); messagebox.showerror('Batch replacement rejected', str(exc), parent=self.root)

    def choose_validate(self):
        if not self.session or self.busy: return
        def done(report):
            self.set_text(self.validation, json.dumps(report, indent=2)); self.tabs.select(2)
            self.status.set(f'PC validation PASS: {report["resource_count"]:,} resources verified. Console acceptance untested.')
        self.submit('Validating current resource layout and contents…', self.session.validate, done)

    def show_folder(self):
        if self.last_project and not self.busy:
            os.startfile(self.last_project)

    def choose_nested(self):
        if self.busy or not self.session or not self.tree.selection(): return
        ident = self.tree.selection()[0]
        if ident not in self.session.resources: return
        def done(report):
            self.nested_resource, self.nested_report = ident, report
            self.nested_tree.delete(*self.nested_tree.get_children())
            self.nested_text.delete('1.0', 'end')
            for index, item in enumerate(report.get('strings', [])):
                self.nested_tree.insert('', 'end', iid=str(index), values=(item['id'], item['text']))
            self.nested_info.set('Equal UTF-16 byte-length edits preserve references; shared storage edits are rejected.' if 'strings' in report else
                                 'XML inspection/export only: atlas dimensions and dependent UV metadata are not editable.')
            if 'strings' not in report: self.nested_text.insert('1.0', json.dumps(report, indent=2))
            self.tabs.select(3)
        self.submit('Decoding nested structure…', lambda: self.session.inspect_nested(ident), done)

    def nested_selected(self, _=None):
        if not self.nested_report or not self.nested_tree.selection(): return
        item = self.nested_report['strings'][int(self.nested_tree.selection()[0])]
        self.nested_text.delete('1.0', 'end'); self.nested_text.insert('1.0', item['text'])

    def stage_nested(self):
        if self.busy or not self.nested_report or not self.nested_tree.selection(): return
        item = self.nested_report['strings'][int(self.nested_tree.selection()[0])]
        text = self.nested_text.get('1.0', 'end-1c')
        def done(report):
            self.nested_report = self.session.inspect_nested(self.nested_resource)
            self.imported(report)
        self.submit('Validating nested string edit…', lambda: self.session.stage_string(self.nested_resource, item['id'], text), done)

    def extract_nested(self):
        if self.busy or not self.nested_resource: return
        folder = self.output_folder()
        if folder: self.submit('Extracting nested raw and decoded resources…',
                                lambda: self.session.export_nested(self.nested_resource, folder),
                                lambda x: self.status.set('Nested resources extracted: ' + x['directory']))

    def show_gallery(self):
        if self.busy or not self.session: return
        identifiers = [x['id'] for x in self.session.current_container.resources if x['kind'] in ('png', 'dds') and x['image']]
        window = tk.Toplevel(self.root); window.title('Resource thumbnails — pages of 48'); window.geometry('900x740')
        bar = ttk.Frame(window); bar.pack(fill='x'); body = ttk.Frame(window); body.pack(fill='both', expand=True)
        state = {'page': 0, 'photos': []}
        label = ttk.Label(bar); label.pack(side='left', padx=10)
        def show(page):
            if self.busy: return
            start = max(0, min(page, max(0, (len(identifiers) - 1) // 48))) * 48
            state['page'] = start // 48
            def work():
                result = []
                for ident in identifiers[start:start + 48]:
                    try: result.append((ident, self.session.preview(ident, (88, 68)), None))
                    except Exception as exc: result.append((ident, None, str(exc)))
                return result
            def done(items):
                if not window.winfo_exists(): return
                for child in body.winfo_children(): child.destroy()
                state['photos'] = []
                label.configure(text=f'{start + 1}–{start + len(items)} of {len(identifiers):,}')
                for index, (ident, image, error) in enumerate(items):
                    frame = ttk.Frame(body, padding=5); frame.grid(row=index // 6, column=index % 6, sticky='nsew')
                    if image:
                        photo = ImageTk.PhotoImage(image, master=window); state['photos'].append(photo)
                        widget = ttk.Label(frame, image=photo)
                    else: widget = ttk.Label(frame, text='Preview unavailable')
                    widget.pack(); ttk.Label(frame, text=ident).pack()
                    widget.bind('<Button-1>', lambda _, i=ident: self.gallery_select(i))
                self.status.set('Thumbnail page loaded.')
            self.submit('Decoding thumbnail page…', work, done)
        ttk.Button(bar, text='Previous', command=lambda: show(max(0, state['page'] - 1))).pack(side='left')
        ttk.Button(bar, text='Next', command=lambda: show(state['page'] + 1)).pack(side='left')
        show(0)

    def gallery_select(self, ident):
        if self.tree.exists(ident):
            self.tree.selection_set(ident); self.tree.see(ident); self.select()

    def close(self):
        if self.busy:
            self.status.set('An operation is running. Wait for it to finish before closing.')
        else:
            self.root.destroy()


def launch(path=None):
    root = tk.Tk()
    app = Studio(root)
    if path: root.after(100, lambda: app.open_path(path))
    root.mainloop()
