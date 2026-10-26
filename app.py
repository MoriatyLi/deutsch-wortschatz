"""Deutsch Wortschatz: a local, editable German vocabulary notebook."""
import json
import logging
import os
import sqlite3
from pathlib import Path

import streamlit as st

from export_obsidian import DEFAULT_TABLE_PATH, batch_sync, csv_export, sync_entry, save_word_table
from providers import HttpClient, Providers
from vocab import BASE_DIR, Store, Vocabulary
from offline_dictionary import stats as dictionary_stats
from prepare_offline import activate as activate_offline
from offline_tts import (DEFAULT_SPEECH_PATH, available as speech_available,
    ensure_audio, fill_missing, clear_missing_audio_warnings)
from fuzzy_words import suggest as suggest_words

st.set_page_config(page_title='Deutsch Wortschatz · 德语词库', page_icon='📖', layout='wide')
DATA_DIR = Path(os.environ.get('DEUTSCH_VOCAB_DATA_DIR', BASE_DIR / 'data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=DATA_DIR / 'app.log', level=logging.INFO, encoding='utf-8')
store = Store(DATA_DIR / 'vocab.db')


@st.cache_resource
def http_client():
    return HttpClient()


providers = Providers(DATA_DIR / 'audio', store, http_client())
service = Vocabulary(store, providers)


def flash(message, warnings=()):
    st.session_state['flash'] = (message, list(warnings))
    st.rerun()


def sync_after_edit(row, force=False):
    messages = []
    if force or store.get_setting('auto_save_word_table') == '1':
        try:
            path = save_word_table(store, audio_root=DATA_DIR / 'audio')
            messages.append(f'已更新 Obsidian 单词表：{path}')
        except (OSError, ValueError, RuntimeError) as exc:
            messages.append(f'词库已保存，单词表更新失败：{exc}')
    if row is not None and store.get_setting('auto_sync') == '1':
        try:
            path = sync_entry(store, row, store.get_setting('vault'), DATA_DIR / 'audio')
            messages.append(f'已同步逐词笔记：{path.name}')
        except (OSError, ValueError, RuntimeError) as exc:
            messages.append(f'词条已保存，逐词笔记同步失败：{exc}')
    return messages


def local_pronunciation(row):
    if store.get_setting('offline_speech', '1') != '1':
        return row, False, []
    try:
        row, changed = ensure_audio(store, row, DATA_DIR / 'audio',
            store.get_setting('offline_speech_path') or DEFAULT_SPEECH_PATH)
        return row, changed, []
    except (OSError, ValueError, RuntimeError) as exc:
        return row, False, [f'本地德语发音未生成：{exc}']


with st.sidebar:
    st.title('📖 Wortschatz')
    st.caption('你的本地德语词库')
    with st.form('word_table_settings'):
        st.subheader('Obsidian 单词表')
        table_path_input = st.text_input('单词表保存位置（Markdown 文件）',
            value=store.get_setting('word_table_path') or str(DEFAULT_TABLE_PATH), key='word_table_path_input')
        table_auto_input = st.checkbox('保存词条后自动更新单词表',
            value=store.get_setting('auto_save_word_table') == '1', key='auto_save_word_table_input')
        st.caption('保存完整词库到一个文件；个人笔记请写在自动更新区域外。')
        if st.form_submit_button('确定位置并保存单词表', key='save_word_table'):
            try:
                if not table_path_input.strip():
                    raise ValueError('请输入单词表的完整保存路径。')
                path = save_word_table(store, table_path_input.strip(), DATA_DIR / 'audio')
                store.set_setting('word_table_path', str(path))
                store.set_setting('auto_save_word_table', int(table_auto_input))
                flash(f'单词表已保存到：{path}')
            except (OSError, ValueError, RuntimeError) as exc:
                st.error(f'单词表未保存：{exc}')
    with st.form('settings'):
        st.subheader('查询设置')
        online_input = st.checkbox('启用在线词典与中文翻译', value=store.get_setting('online', '1') == '1')
        tts_input = st.checkbox('无录音时允许 Edge TTS', value=store.get_setting('tts') == '1')
        st.caption('在线查询仅发送输入词语。TTS 会发送该词给 Microsoft。')
        offline_input = st.text_input('本地词典（SQLite / JSONL）', value=store.get_setting('offline_path'))
        st.subheader('本地德语朗读')
        speech_input = st.checkbox('无录音时自动生成本地德语发音',
            value=store.get_setting('offline_speech', '1') == '1', key='offline_speech_input')
        speech_path_input = st.text_input('本地德语语音目录（D盘）',
            value=store.get_setting('offline_speech_path') or str(DEFAULT_SPEECH_PATH), key='offline_speech_path_input')
        st.caption('语音资源放在 D 盘；合成不联网，已有人声录音会保留。')
        st.subheader('Obsidian 逐词笔记（可选）')
        vault_input = st.text_input('Vault 文件夹', value=store.get_setting('vault'), placeholder='选择已有 Vault 的完整路径')
        auto_input = st.checkbox('保存后自动同步', value=store.get_setting('auto_sync') == '1')
        if st.form_submit_button('保存设置'):
            if speech_input and Path(speech_path_input.strip()).drive.upper() != 'D:':
                st.error('本地语音资源目录必须位于 D 盘。')
            elif speech_input and not speech_available(speech_path_input.strip()):
                st.error('该目录没有完整的德语语音资源，请检查路径。')
            else:
                for key, value in {'online': int(online_input), 'tts': int(tts_input), 'offline_path': offline_input.strip(),
                    'vault': vault_input.strip(), 'auto_sync': int(auto_input), 'offline_speech': int(speech_input),
                    'offline_speech_path': speech_path_input.strip()}.items():
                    store.set_setting(key, value)
                flash('设置已保存。')
    speech_path = store.get_setting('offline_speech_path') or str(DEFAULT_SPEECH_PATH)
    if speech_available(speech_path):
        st.caption('本地德语语音已就绪 · eSpeak NG · 合成发音')
    if st.button('补全缺失的离线读音', disabled=not speech_available(speech_path), width='stretch'):
        with st.spinner('正在本地生成德语发音…'):
            count, errors = fill_missing(store, DATA_DIR / 'audio', speech_path)
            if count and store.get_setting('auto_save_word_table') == '1':
                try:
                    save_word_table(store, audio_root=DATA_DIR / 'audio')
                except (OSError, ValueError, RuntimeError) as exc:
                    errors.append(f'发音已保存，Obsidian 更新失败：{exc}')
        flash(f'已补全 {count} 条离线读音，已有录音保留。', errors)
    local_path = store.get_setting('offline_path')
    if store.get_setting('online', '1') == '0':
        st.success('运行模式：完全离线')
    if local_path and Path(local_path).suffix.lower() in {'.db', '.sqlite', '.sqlite3'}:
        try:
            local_stats = dictionary_stats(local_path)
            st.caption(f"本地词典：{local_stats['words']:,} 个词形 · {local_stats['entries']:,} 个义项")
        except (OSError, ValueError) as exc:
            st.warning(str(exc))
    with st.expander('导入离线词典'):
        import_path = st.text_input('已下载的词典 JSONL 路径', key='dictionary_import_path')
        if st.button('建立索引并启用离线模式'):
            try:
                with st.spinner('正在建立本地词典索引…'):
                    report = activate_offline(import_path, DATA_DIR / 'dictionaries' / 'de-zh.db', store)
                flash(f"本地词典已就绪：{report['words']:,} 个词形。已关闭在线查询和 Edge TTS。")
            except (OSError, ValueError) as exc:
                st.error(str(exc))
    st.caption(f'个人词库和录音保存在：{DATA_DIR.resolve()}。备份时请复制整个文件夹。')
    if st.button('全量同步到 Obsidian', width='stretch'):
        with st.spinner('正在同步本地笔记…'):
            succeeded, errors = batch_sync(store, store.get_setting('vault'), DATA_DIR / 'audio')
        flash(f'同步成功 {succeeded} 条。', errors)

options = dict(online=store.get_setting('online', '1') == '1', tts=store.get_setting('tts') == '1', offline_path=store.get_setting('offline_path') or None)
if not options['online']:
    st.caption('本地离线查词 · 不访问在线词典或翻译服务')

st.title('Deutsch Wortschatz')
st.caption('记下一个词，慢慢积累你的德语。词典、发音与校对记录，留在同一处。')
if 'flash' in st.session_state:
    message, warnings = st.session_state.pop('flash')
    if warnings:
        st.info(message)
    else:
        st.success(message)
    for warning in warnings:
        st.warning(warning)

new_word = st.text_input('德语单词或短语', key='new_word', placeholder='例如 Wasser、sprechen、Guten Morgen',
    help='输入后按 Enter 或点击其他位置，可查看本地候选词。')
chosen_word = None
if new_word.strip() and options['offline_path']:
    try:
        suggestions = suggest_words(new_word, options['offline_path'])
        if suggestions:
            choices = {item['word']: item for item in suggestions}
            def candidate_label(value):
                if value is None:
                    return '按原输入加入：' + new_word.strip()
                item = choices[value]
                return ' · '.join(part for part in (value,item['article'],item['meaning'],item['match']) if part)
            chosen_word = st.selectbox('你要找的是哪个词？', [None,*choices],
                format_func=candidate_label,key='word_candidate_' + new_word)
            st.caption('选择词典中的词形后点击“加入词库”；也可按原输入加入。')
        else:
            st.caption('未找到相近词，仍可按原输入加入并手动校对。')
    except (OSError,ValueError,sqlite3.Error) as exc:
        st.caption(f'本地候选词暂不可用：{exc}')
submitted = st.button('加入词库', key='add_word', type='primary')
if submitted:
    try:
        with st.spinner('正在查询并保存…'):
            row, created, warnings = service.add(chosen_word or new_word, **options)
            row, audio_created, speech_errors = local_pronunciation(row)
            if row.get('audio_file'):
                warnings = clear_missing_audio_warnings(warnings)
            warnings.extend(speech_errors)
        st.session_state['selected_id'] = row['id']
        st.session_state.pop('entry_picker', None)
        st.session_state.pop('editor_id', None)
        if created or audio_created:
            warnings.extend(sync_after_edit(row))
        flash('已加入词库。' if created else '此词已在词库中，已打开原词条。', warnings)
    except (OSError, ValueError) as exc:
        st.error(str(exc))

search = st.text_input('搜索词库', placeholder='搜索德语或中文', key='search')
rows = store.list(search)
left, right = st.columns([1, 2], gap='large')
with left:
    st.subheader(f'词库 · {len(rows)}')
    if rows:
        ids = [r['id'] for r in rows]
        selected = st.session_state.get('selected_id')
        index = ids.index(selected) if selected in ids else 0
        labels = {r['id']: f"{r['word']}  ·  {r['chinese_meaning'] or '释义待补充'}" for r in rows}
        entry_id = st.selectbox('选择词条', ids, index=index, format_func=lambda i: labels[i], key='entry_picker')
        st.session_state['selected_id'] = entry_id
        st.dataframe([{'德语': r['word'], '冠词': r['article'] or '—', '释义': r['chinese_meaning'] or '待补充', '校对': '已复核' if r['meaning_reviewed'] else '待复核'} for r in rows], hide_index=True, width='stretch')
    else:
        entry_id = None
        st.info('还没有匹配的词条。输入一个德语词开始。')
    st.download_button('导出全部 CSV', csv_export(store.list()), file_name='deutsch-wortschatz.csv', mime='text/csv', width='stretch')

with right:
    if entry_id is not None:
        row = store.get(entry_id)
        row, audio_created, speech_errors = local_pronunciation(row)
        if audio_created:
            speech_errors.extend(sync_after_edit(row))
        for speech_error in speech_errors:
            st.caption(speech_error)
        st.subheader(row['word'])
        if row.get('lookup_status') == 'failed':
            st.error('自动补全失败：在线词典或翻译服务未连通。请检查网络/代理后点击“重新查询”。')
        elif not any(row.get(field) for field in ('ipa', 'part_of_speech', 'chinese_meaning')):
            st.info('此词尚无词典信息。重复添加不会重新请求，请使用下方“重新查询”重试。')
        if row.get('dictionary_word') and row['dictionary_word'] != row['word']:
            st.caption('词典匹配词形：' + row['dictionary_word'] + '（原输入保留）')
        lookup_warnings = json.loads(row.get('lookup_warnings_json') or '[]')
        if lookup_warnings:
            with st.expander('自动补全详情', expanded=row.get('lookup_status') == 'failed'):
                for lookup_warning in lookup_warnings:
                    st.write(lookup_warning)
        status = '已人工复核' if row['meaning_reviewed'] else '释义待复核' if row['chinese_meaning'] else '释义待补充'
        st.caption(f"{status} · {row['meaning_source'] or '尚无释义来源'}")
        candidates = json.loads(row['candidates_json'] or '[]')
        pronunciation_variants = sorted({ipa for candidate in candidates for ipa in candidate.get('pronunciations', [])})
        if not row['ipa'] and pronunciation_variants:
            st.caption('词典记录了多个读音，可对照原文核对：' + '；'.join(pronunciation_variants))
        if len(candidates) > 1:
            st.warning('此词有多个候选义项。选择对应词义后再核对中文释义与发音。')
        if candidates:
            candidate_map = {c['sense_id']: c for c in candidates}
            choices = [None, *candidate_map]
            current = row['sense_id'] if row['sense_id'] in candidate_map else None
            choice = st.selectbox('词典义项候选', choices, index=choices.index(current), key=f'sense_{entry_id}', format_func=lambda value: '请选择义项…' if value is None else ' · '.join(str(candidate_map[value].get(k) or '—') for k in ('headword', 'article', 'part_of_speech', 'sense', 'ipa')))
            if st.button('采用此义项并获取发音', disabled=choice is None):
                row = store.select_sense(entry_id, choice)
                warnings = []
                if options['online']:
                    with st.spinner('获取所选义项的录音…'):
                        audio, warnings = providers.audio(row['word'], candidate_map[choice], tts=options['tts'])
                    if audio:
                        row = store.attach_audio(entry_id, audio)
                row, _, speech_errors = local_pronunciation(row)
                warnings.extend(speech_errors)
                st.session_state.pop('editor_id', None)
                warnings.extend(sync_after_edit(row))
                flash('已采用所选义项，请核对中文释义。', warnings)
        if row['source_url']:
            st.link_button('查看德语词典原文', row['source_url'])
        elif candidates:
            st.caption('词典来源：' + candidates[0].get('source', '本地词典'))
        if row['audio_file']:
            audio_path = (DATA_DIR / 'audio' / row['audio_file']).resolve()
            if audio_path.is_relative_to((DATA_DIR / 'audio').resolve()) and audio_path.is_file() and audio_path.stat().st_size <= 15 * 1024 * 1024:
                st.audio(audio_path.read_bytes(), format={'.ogg': 'audio/ogg', '.oga': 'audio/ogg', '.opus': 'audio/ogg', '.wav': 'audio/wav', '.flac': 'audio/flac'}.get(audio_path.suffix, 'audio/mpeg'))
                st.caption('本地德语合成发音 · eSpeak NG · 请核对读音' if row['audio_kind'] == 'offline_tts'
                    else 'TTS 合成发音 · 请核对读音' if row['audio_kind'] == 'tts' else '词典录音 · Wikimedia Commons')
                st.caption((row['audio_license'] or '许可待补充') + ' · ' + (row['attribution'] or ''))
            else:
                st.warning('本地音频文件缺失或路径不安全，请重新获取发音。')
        else:
            st.caption('暂无发音。可在设置中启用本地德语朗读，或补全缺失的离线读音。')
        meanings = json.loads(row['meaning_candidates_json'] or '[]')
        if meanings:
            with st.expander('中文释义候选与出处'):
                for meaning_index, meaning in enumerate(meanings):
                    st.write(meaning['text'])
                    if st.button('采用这条中文释义', key=f'meaning_{entry_id}_{meaning_index}'):
                        row = store.select_meaning(entry_id, meaning_index)
                        st.session_state.pop('editor_id', None)
                        flash('已采用中文释义，仍需人工复核。', sync_after_edit(row))
                    st.caption(meaning.get('source', ''))
                    if meaning.get('source_url'):
                        st.link_button('释义来源', meaning['source_url'])

        if st.session_state.get('editor_id') != entry_id:
            for key, field in [('edit_ipa', 'ipa'), ('edit_pos', 'part_of_speech'), ('edit_article', 'article'), ('edit_meaning', 'chinese_meaning'), ('edit_note', 'note')]:
                st.session_state[key] = row[field] or ''
            st.session_state['edit_reviewed'] = bool(row['meaning_reviewed'])
            st.session_state['editor_id'] = entry_id
        with st.form('edit_entry'):
            st.text_area('中文释义', key='edit_meaning')
            a, b = st.columns(2)
            a.text_input('词性（如 Substantiv / Verb）', key='edit_pos')
            b.text_input('冠词（der / die / das）', key='edit_article')
            st.text_input('IPA', key='edit_ipa')
            st.text_area('词条备注', key='edit_note')
            st.checkbox('我已核对中文释义', key='edit_reviewed')
            save = st.form_submit_button('保存校对', key='save_entry', type='primary')
        if save:
            values = {field: st.session_state[key].strip() or None for key, field in [('edit_ipa', 'ipa'), ('edit_pos', 'part_of_speech'), ('edit_article', 'article'), ('edit_meaning', 'chinese_meaning'), ('edit_note', 'note')]}
            values['meaning_reviewed'] = bool(st.session_state['edit_reviewed'] and values['chinese_meaning'])
            changed = {k: v for k, v in values.items() if v != row[k]}
            try:
                row = store.update(entry_id, **changed)
                st.session_state.pop('editor_id', None)
                flash('校对已保存。', sync_after_edit(row))
            except (OSError, ValueError) as exc:
                st.error(str(exc))
        action1, action2 = st.columns(2)
        if action1.button('重新查询（保留人工修改）', width='stretch'):
            with st.spinner('重新查询词典…'):
                fields, warnings = providers.lookup(row.get('dictionary_word') or row['word'], force=True, **options)
            row = store.refresh(entry_id, fields)
            row, _, speech_errors = local_pronunciation(row)
            if row.get('audio_file'):
                warnings = clear_missing_audio_warnings(warnings)
            warnings.extend(speech_errors)
            st.session_state.pop('editor_id', None)
            warnings.extend(sync_after_edit(row))
            message = '已保留词条，自动补全未成功。' if fields.get('lookup_status') == 'failed' else '查询已更新，人工修改已保留。'
            flash(message, warnings)
        if action2.button('更新 Obsidian 单词表', width='stretch'):
            messages = sync_after_edit(row, force=True)
            flash('单词表保存操作已结束。', messages)
        if row['sync_status']:
            st.caption(f"最近同步：{row['sync_status']} · {row['synced_at'] or '未成功'}")
        with st.expander('删除词条'):
            confirm = st.checkbox('确认从本地词库删除（自动单词表会更新，逐词笔记保留）')
            if st.button('删除此词条', disabled=not confirm):
                store.delete(entry_id)
                st.session_state.pop('selected_id', None)
                st.session_state.pop('editor_id', None)
                flash('词条已删除，逐词笔记和音频仍保留。', sync_after_edit(None))
