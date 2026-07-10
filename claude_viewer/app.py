"""NiceGUI web interface for browsing and searching Claude Code sessions."""
from __future__ import annotations

import html
from types import SimpleNamespace

from nicegui import run, ui

from . import config as config_mod
from . import export as export_mod
from . import search as search_mod
from . import store

semantic_index = search_mod.SemanticIndex()


def register_pages() -> None:
    @ui.page('/')
    def main_page() -> None:
        build_page()


def build_page() -> None:  # noqa: PLR0915 - one page, one builder
    cfg = config_mod.load_config()
    state = SimpleNamespace(
        projects=store.list_projects(),
        project=None,
        session=None,
        highlight=None,
        show_tools=False,
        results=[],
        results_note='',
        searched=False,
    )

    # ------------------------------------------------------------- helpers

    def current_scope_pairs() -> list:
        only = state.project if scope_select.value == 'Current project' else None
        return search_mod.scope_pairs(state.projects, only)

    def select_project(project: store.Project) -> None:
        state.project = project
        state.session = None
        state.highlight = None
        project_list.refresh()
        browse_view.refresh()
        tabs.set_value('browse')
        update_index_status()

    def select_session(path) -> None:
        state.session = store.load_session(path)
        state.highlight = None
        browse_view.refresh()

    def back_to_sessions() -> None:
        state.session = None
        state.highlight = None
        browse_view.refresh()

    def reload_projects() -> None:
        state.projects = store.list_projects()
        state.project = None
        state.session = None
        project_list.refresh()
        browse_view.refresh()
        update_index_status()
        ui.notify(f'Found {len(state.projects)} projects', type='positive')

    def open_hit(hit: search_mod.Hit) -> None:
        state.project = hit.project
        state.session = store.load_session(hit.session_path)
        state.highlight = hit.uuid
        project_list.refresh()
        browse_view.refresh()
        tabs.set_value('browse')
        ui.timer(0.3, lambda: ui.run_javascript(
            f'document.querySelector(\'[data-msg="{state.highlight}"]\')'
            f'?.scrollIntoView({{behavior: "smooth", block: "center"}})'), once=True)

    # ------------------------------------------------------------- search

    async def run_search() -> None:
        query = (query_input.value or '').strip()
        if not query:
            ui.notify('Enter a search query', type='warning')
            return
        if scope_select.value == 'Current project' and state.project is None:
            ui.notify('No project selected — choose one in the sidebar first', type='warning')
            return
        pairs = current_scope_pairs()
        state.results_note = ''
        search_button.disable()
        try:
            if mode_toggle.value == 'Text':
                state.results = await run.io_bound(search_mod.text_search, pairs, query)
            else:
                try:
                    state.results, missing = await semantic_index.search(
                        pairs, cfg, query, top_k=int(cfg['top_k']))
                except Exception as exc:  # noqa: BLE001 - surface any server error
                    ui.notify(f'Semantic search failed: {exc}', type='negative', timeout=8000)
                    return
                if missing:
                    state.results_note = (f'{missing} session(s) are not in the index yet — '
                                          f'click "Build index" to include them.')
        finally:
            search_button.enable()
        state.searched = True
        results_view.refresh()

    async def build_index() -> None:
        pairs = current_scope_pairs()
        build_button.disable()
        index_progress.visible = True

        def on_progress(done: int, total: int, label: str) -> None:
            index_progress.set_value(done / max(total, 1))
            index_status.set_text(f'Indexing {done}/{total}: {label}')

        try:
            built = await semantic_index.build(pairs, cfg, on_progress)
            ui.notify(f'Index up to date ({built} session(s) embedded)', type='positive')
        except Exception as exc:  # noqa: BLE001 - surface any server error
            ui.notify(f'Indexing failed: {exc} — check the LLM server settings (gear icon)',
                      type='negative', timeout=8000)
        finally:
            build_button.enable()
            index_progress.visible = False
            update_index_status()

    def update_index_status() -> None:
        indexed, total = semantic_index.status(current_scope_pairs(), cfg['embedding_model'])
        index_status.set_text(f'Semantic index: {indexed}/{total} sessions embedded '
                              f'(model: {cfg["embedding_model"]})')

    # ------------------------------------------------------------ settings

    def open_settings() -> None:
        with ui.dialog() as dialog, ui.card().classes('w-[28rem]'):
            ui.label('LLM server (OpenAI-compatible API)').classes('text-lg font-medium')
            url_input = ui.input('Base URL', value=cfg['base_url'],
                                 placeholder='http://192.168.1.50:11434/v1').classes('w-full')
            key_input = ui.input('API key', value=cfg['api_key'], password=True,
                                 password_toggle_button=True).classes('w-full')
            model_input = ui.input('Embedding model', value=cfg['embedding_model'],
                                   placeholder='nomic-embed-text').classes('w-full')
            topk_input = ui.number('Semantic results (top k)', value=cfg['top_k'],
                                   min=1, max=50, precision=0).classes('w-full')
            test_result = ui.label('').classes('text-sm')

            async def test() -> None:
                trial = {'base_url': url_input.value, 'api_key': key_input.value,
                         'embedding_model': model_input.value, 'top_k': cfg['top_k']}
                test_result.set_text('Testing…')
                try:
                    test_result.set_text(await search_mod.test_connection(trial))
                    test_result.classes(replace='text-sm text-positive')
                except Exception as exc:  # noqa: BLE001 - surface any server error
                    test_result.set_text(f'Failed: {exc}')
                    test_result.classes(replace='text-sm text-negative')

            def save() -> None:
                cfg.update(base_url=url_input.value.strip(), api_key=key_input.value,
                           embedding_model=model_input.value.strip(),
                           top_k=int(topk_input.value or 10))
                config_mod.save_config(cfg)
                update_index_status()
                dialog.close()
                ui.notify('Settings saved', type='positive')

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Test connection', on_click=test).props('outline')
                ui.button('Cancel', on_click=dialog.close).props('flat')
                ui.button('Save', on_click=save)
        dialog.open()

    # ----------------------------------------------------------- renderers

    @ui.refreshable
    def project_list() -> None:
        if not state.projects:
            ui.label(f'No projects found in {store.PROJECTS_DIR}').classes('text-sm text-grey-7 p-2')
            return
        with ui.list().props('dense').classes('w-full'):
            for project in state.projects:
                selected = 'bg-blue-2' if project is state.project else ''
                with ui.item(on_click=lambda p=project: select_project(p)) \
                        .props('clickable').classes(f'rounded {selected}'):
                    with ui.item_section():
                        ui.label(project.name).classes('font-medium')
                        ui.label(f'{len(project.session_files)} session(s) · {project.real_path}') \
                            .classes('text-xs text-grey-7')

    def render_message(message: store.Message) -> None:
        if message.role == 'tool':
            if not state.show_tools:
                return
            with ui.row().classes('items-center gap-2 pl-6 w-full'):
                ui.icon('build').classes('text-grey-6').props('size=xs')
                ui.label(message.text).classes('text-grey-7 text-xs font-mono')
            return
        is_user = message.role == 'user'
        bg = 'bg-blue-1' if is_user else 'bg-white'
        outline = ' outline outline-2 outline-orange-400' if message.uuid == state.highlight else ''
        with ui.card().tight().classes(f'w-full {bg}{outline}').props(f'data-msg="{message.uuid}"'):
            with ui.card_section().classes('w-full py-2'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('person' if is_user else 'smart_toy') \
                        .classes('text-primary' if is_user else 'text-teal-7').props('size=xs')
                    ui.label('You' if is_user else 'Claude').classes('text-xs font-medium')
                    ui.label(store.format_timestamp(message.timestamp)).classes('text-xs text-grey-6')
                ui.markdown(message.text).classes('w-full')

    @ui.refreshable
    def browse_view() -> None:
        if state.project is None:
            ui.label('Select a project in the sidebar to see its sessions.') \
                .classes('text-grey-7 mt-8')
            return
        if state.session is None:
            ui.label(state.project.real_path).classes('text-grey-7 text-sm')
            for path in state.project.session_files:
                data = store.load_session(path)
                with ui.card().classes('w-full cursor-pointer hover:bg-blue-1') \
                        .on('click', lambda p=path: select_session(p)):
                    ui.label(data.title).classes('font-medium')
                    ui.label(f'{store.format_timestamp(data.started)} · {data.prompt_count} prompt(s) '
                             f'· {path.name}').classes('text-xs text-grey-7')
            return
        with ui.row().classes('items-center w-full'):
            ui.button(icon='arrow_back', on_click=back_to_sessions).props('flat round')
            with ui.column().classes('gap-0'):
                ui.label(state.session.title).classes('text-lg font-medium')
                ui.label(f'{state.project.real_path} · {store.format_timestamp(state.session.started)}') \
                    .classes('text-xs text-grey-7')
            ui.space()

            def toggle_tools(event) -> None:
                state.show_tools = event.value
                browse_view.refresh()

            ui.switch('Show tool calls', value=state.show_tools, on_change=toggle_tools)

            async def export_pdf() -> None:
                session, project = state.session, state.project
                try:
                    pdf_bytes = await run.cpu_bound(
                        export_mod.session_to_pdf, project.real_path, session, state.show_tools)
                except Exception as exc:  # noqa: BLE001 - surface any render error
                    ui.notify(f'PDF export failed: {exc}', type='negative', timeout=8000)
                    return
                ui.download.content(pdf_bytes, export_mod.pdf_filename(session.title))

            ui.button(icon='picture_as_pdf', on_click=export_pdf).props('flat round') \
                .tooltip('Export conversation to PDF (tool calls included if shown)')
        for message in state.session.messages:
            render_message(message)

    @ui.refreshable
    def results_view() -> None:
        if state.results_note:
            ui.label(state.results_note).classes('text-orange-8 text-sm')
        if state.searched and not state.results:
            ui.label('No matches.').classes('text-grey-7')
        for hit in state.results:
            with ui.card().classes('w-full cursor-pointer hover:bg-blue-1') \
                    .on('click', lambda h=hit: open_hit(h)):
                with ui.row().classes('items-center gap-2 w-full'):
                    ui.label(hit.project.name).classes('text-xs font-medium text-primary')
                    ui.label(hit.session_title).classes('text-xs text-grey-7')
                    ui.space()
                    if hit.score is not None:
                        ui.badge(f'{hit.score:.0%}').props('color=teal-7')
                    ui.badge('prompt' if hit.role == 'user' else 'response') \
                        .props(f'color={"primary" if hit.role == "user" else "grey-7"} outline')
                if hit.span:
                    before = html.escape(hit.preview[:hit.span[0]])
                    match = html.escape(hit.preview[hit.span[0]:hit.span[1]])
                    after = html.escape(hit.preview[hit.span[1]:])
                    ui.html(f'<div class="text-sm">…{before}<mark>{match}</mark>{after}…</div>')
                else:
                    ui.label(f'{hit.preview}…').classes('text-sm')

    # -------------------------------------------------------------- layout

    with ui.header().classes('items-center'):
        ui.button(icon='menu', on_click=lambda: drawer.toggle()).props('flat round color=white')
        ui.label('Claude Code Viewer').classes('text-lg font-medium')
        ui.space()
        ui.button(icon='settings', on_click=open_settings).props('flat round color=white')

    with ui.left_drawer(value=True, bordered=True).classes('bg-grey-1') as drawer:
        with ui.row().classes('items-center w-full'):
            ui.label('Projects').classes('font-medium')
            ui.space()
            ui.button(icon='refresh', on_click=reload_projects).props('flat round dense') \
                .tooltip('Rescan ~/.claude/projects')
        project_list()

    with ui.tabs().classes('w-full') as tabs:
        ui.tab('browse', label='Browse', icon='folder_open')
        ui.tab('search', label='Search', icon='search')

    with ui.tab_panels(tabs, value='browse').classes('w-full max-w-4xl mx-auto'):
        with ui.tab_panel('browse'):
            browse_view()
        with ui.tab_panel('search'):
            with ui.row().classes('items-center w-full gap-3'):
                query_input = ui.input('Search query').classes('grow') \
                    .on('keydown.enter', run_search)
                mode_toggle = ui.toggle(['Text', 'Semantic'], value='Text')
                scope_select = ui.select(['All projects', 'Current project'], value='All projects',
                                         on_change=lambda: update_index_status())
                search_button = ui.button('Search', icon='search', on_click=run_search)
            with ui.row().classes('items-center w-full gap-3'):
                index_status = ui.label('').classes('text-xs text-grey-7')
                ui.space()
                build_button = ui.button('Build index', icon='sync', on_click=build_index) \
                    .props('outline dense') \
                    .tooltip('Embed all sessions in scope via the configured LLM server')
            index_progress = ui.linear_progress(value=0, show_value=False).classes('w-full')
            index_progress.visible = False
            results_view()

    update_index_status()
