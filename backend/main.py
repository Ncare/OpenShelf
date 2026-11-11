import base64
import io
import zipfile
import json
import os
import re
import sqlite3
import uuid
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DATA = Path(os.environ.get('DATA_DIR', './data'))
IMAGES = DATA / 'images'
IMAGES.mkdir(parents=True, exist_ok=True)
DB = DATA / 'app.db'
app = FastAPI(title='开源集')
app.mount('/images', StaticFiles(directory=IMAGES), name='images')

@contextmanager
def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

with db() as conn:
    conn.executescript('''CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, repo TEXT UNIQUE NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '', platforms TEXT NOT NULL DEFAULT '[]', tags TEXT NOT NULL DEFAULT '[]', screenshot TEXT NOT NULL DEFAULT '', stars INTEGER, license TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '', published INTEGER NOT NULL DEFAULT 0); CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY); CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);''')
    conn.execute("CREATE TABLE IF NOT EXISTS ai_usage (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT (datetime('now')), task TEXT NOT NULL, repo TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER)")
    usage_columns = {row['name'] for row in conn.execute('PRAGMA table_info(ai_usage)')}
    for column in ('request_body', 'response_body'):
        if column not in usage_columns:
            conn.execute(f'ALTER TABLE ai_usage ADD COLUMN {column} TEXT')
    if 'icon' not in {row['name'] for row in conn.execute('PRAGMA table_info(projects)')}:
        conn.execute("ALTER TABLE projects ADD COLUMN icon TEXT NOT NULL DEFAULT ''")
    if not conn.execute('SELECT 1 FROM categories').fetchone():
        conn.executemany('INSERT INTO categories VALUES (?)', [(x,) for x in ['效率工具', '开发工具', '设计创作', '媒体工具', '文件管理', '下载工具', '网络工具', '系统工具', '安全与隐私', '笔记与知识管理', '办公工具', '数据库', '自托管', '科学与教育', '通讯与协作']])

class Project(BaseModel):
    repo: str
    name: str = Field(min_length=1, max_length=200)
    description: str = ''
    category: str = ''
    platforms: list[str] = []
    tags: list[str] = []
    screenshot: str = ''
    icon: str = ''
    stars: int | None = None
    license: str = ''
    updated_at: str = ''
    published: bool = False

class Category(BaseModel):
    name: str = Field(min_length=1, max_length=100)

class Settings(BaseModel):
    ai_enabled: bool = False
    ai_url: str = ''
    ai_model: str = ''
    ai_key: str = ''
    github_token: str = ''

class ModelsRequest(BaseModel):
    ai_url: str
    ai_key: str = ''

class RepoRequest(BaseModel):
    repo: str

class ImageRequest(BaseModel):
    url: str

def row_project(row):
    result = dict(row)
    for key in ('platforms', 'tags'):
        result[key] = json.loads(result[key])
    result['published'] = bool(result['published'])
    return result

def settings():
    with db() as conn:
        return {r['key']: r['value'] for r in conn.execute('SELECT * FROM settings')}

def repo_parts(value):
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?', value.strip(), re.I)
    if not match:
        raise HTTPException(400, '请输入有效的 GitHub 仓库链接')
    return match.group(1), match.group(2)

def normalize_repo(value):
    owner, name = repo_parts(value)
    return f'https://github.com/{owner}/{name}'.lower()

@app.get('/api/projects')
def projects(published: bool = False):
    with db() as conn:
        rows = conn.execute('SELECT * FROM projects' + (' WHERE published = 1' if published else '') + ' ORDER BY id DESC').fetchall()
    return [row_project(r) for r in rows]

@app.get('/api/catalog')
def catalog(offset: int = 0, limit: int = 20, q: str = '', category: str = '', platform: str = ''):
    if offset < 0 or limit < 1 or limit > 100:
        raise HTTPException(400, '分页参数无效')
    conditions = ['published = 1']
    args = []
    if q.strip():
        conditions.append("(instr(lower(name), lower(?)) > 0 OR instr(lower(description), lower(?)) > 0 OR EXISTS (SELECT 1 FROM json_each(projects.tags) WHERE instr(lower(json_each.value), lower(?)) > 0))")
        args.extend([q.strip()] * 3)
    if category:
        conditions.append('category = ?')
        args.append(category)
    if platform:
        conditions.append('EXISTS (SELECT 1 FROM json_each(projects.platforms) WHERE instr(lower(json_each.value), lower(?)) > 0)')
        args.append(platform)
    with db() as conn:
        rows = conn.execute('SELECT * FROM projects WHERE ' + ' AND '.join(conditions) + ' ORDER BY id DESC LIMIT ? OFFSET ?', [*args, limit + 1, offset]).fetchall()
    return {'items': [row_project(row) for row in rows[:limit]], 'has_more': len(rows) > limit}

@app.post('/api/projects')
def create_project(project: Project):
    project.repo = normalize_repo(project.repo)
    values = project.model_dump()
    values['platforms'] = json.dumps(values['platforms'], ensure_ascii=False)
    values['tags'] = json.dumps(values['tags'], ensure_ascii=False)
    try:
        with db() as conn:
            cols = ','.join(values)
            cur = conn.execute(f"INSERT INTO projects ({cols}) VALUES ({','.join('?' for _ in values)})", list(values.values()))
            return {'id': cur.lastrowid}
    except sqlite3.IntegrityError:
        raise HTTPException(409, '这个仓库已经添加过了')

@app.put('/api/projects/{project_id}')
def update_project(project_id: int, project: Project):
    values = project.model_dump()
    values['repo'] = normalize_repo(values['repo'])
    for key in ('platforms', 'tags'):
        values[key] = json.dumps(values[key], ensure_ascii=False)
    try:
        with db() as conn:
            cur = conn.execute('UPDATE projects SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', [*values.values(), project_id])
            if not cur.rowcount:
                raise HTTPException(404, '软件不存在')
    except sqlite3.IntegrityError:
        raise HTTPException(409, '这个仓库已经添加过了')
    return {'ok': True}

@app.delete('/api/projects/{project_id}')
def delete_project(project_id: int):
    with db() as conn:
        conn.execute('DELETE FROM projects WHERE id=?', (project_id,))
    return {'ok': True}

@app.get('/api/categories')
def categories():
    with db() as conn:
        return [dict(r) for r in conn.execute('SELECT c.name, count(p.id) AS count FROM categories c LEFT JOIN projects p ON p.category=c.name GROUP BY c.name ORDER BY c.rowid')]

@app.post('/api/categories')
def add_category(category: Category):
    try:
        with db() as conn:
            conn.execute('INSERT INTO categories VALUES (?)', (category.name.strip(),))
    except sqlite3.IntegrityError:
        raise HTTPException(409, '分类已存在')
    return {'ok': True}

@app.put('/api/categories/{name}')
def rename_category(name: str, category: Category):
    try:
        with db() as conn:
            if not conn.execute('UPDATE categories SET name=? WHERE name=?', (category.name.strip(), name)).rowcount:
                raise HTTPException(404, '分类不存在')
            conn.execute('UPDATE projects SET category=? WHERE category=?', (category.name.strip(), name))
    except sqlite3.IntegrityError:
        raise HTTPException(409, '分类已存在')
    return {'ok': True}

@app.delete('/api/categories/{name}')
def remove_category(name: str):
    with db() as conn:
        if conn.execute('SELECT 1 FROM projects WHERE category=?', (name,)).fetchone():
            raise HTTPException(409, '该分类下还有软件，请先调整分类')
        conn.execute('DELETE FROM categories WHERE name=?', (name,))
    return {'ok': True}

@app.get('/api/settings')
def get_settings():
    saved = settings()
    return {'ai_enabled': saved.get('ai_enabled') == 'true', 'ai_url': saved.get('ai_url', ''), 'ai_model': saved.get('ai_model', ''), 'has_ai_key': bool(saved.get('ai_key')), 'has_github_token': bool(saved.get('github_token'))}

@app.get('/api/settings/ai-key')
def reveal_ai_key():
    return {'ai_key': settings().get('ai_key', '')}

@app.put('/api/settings')
def save_settings(data: Settings):
    values = data.model_dump()
    with db() as conn:
        for key, value in values.items():
            if key in ('ai_key', 'github_token') and not value:
                continue
            conn.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, str(value).lower() if isinstance(value, bool) else value))
    return {'ok': True}

@app.get('/api/ai/usage')
def ai_usage():
    with db() as conn:
        summary = dict(conn.execute("SELECT count(*) AS calls, coalesce(sum(input_tokens),0) AS input_tokens, coalesce(sum(output_tokens),0) AS output_tokens, coalesce(sum(total_tokens),0) AS total_tokens, sum(CASE WHEN total_tokens IS NULL THEN 1 ELSE 0 END) AS missing_usage FROM ai_usage").fetchone())
        rows = [dict(row) for row in conn.execute('SELECT id,created_at,task,repo,model,status,input_tokens,output_tokens,total_tokens FROM ai_usage ORDER BY id DESC LIMIT 100')]
    return {'summary': summary, 'records': rows}

@app.get('/api/ai/usage/{usage_id}')
def ai_usage_detail(usage_id: int):
    with db() as conn:
        row = conn.execute('SELECT * FROM ai_usage WHERE id=?', (usage_id,)).fetchone()
    if not row:
        raise HTTPException(404, '记录不存在')
    return dict(row)

def record_ai_usage(repo, model, status, usage=None, request_body=None, response_body=None):
    usage = usage if isinstance(usage, dict) else {}
    def count(key):
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    with db() as conn:
        conn.execute('INSERT INTO ai_usage (task,repo,model,status,input_tokens,output_tokens,total_tokens,request_body,response_body) VALUES (?,?,?,?,?,?,?,?,?)', ('整理软件信息', repo, model, status, count('prompt_tokens'), count('completion_tokens'), count('total_tokens'), json.dumps(request_body, ensure_ascii=False) if request_body is not None else None, response_body))

@app.post('/api/ai/models')
async def list_models(data: ModelsRequest):
    config = settings()
    url = data.ai_url.strip().rstrip('/')
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(400, '请输入有效的 HTTPS 接口地址')
    key = data.ai_key or (config.get('ai_key', '') if url == config.get('ai_url', '').rstrip('/') else '')
    if not key:
        raise HTTPException(400, '请先输入该服务的 API Key')
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(url + '/models', headers={'Authorization': 'Bearer ' + key})
            if response.status_code != 200:
                raise HTTPException(502, f'获取模型列表失败（服务返回 {response.status_code}）')
            payload = response.json()
            models = sorted({item['id'] for item in payload.get('data', []) if isinstance(item, dict) and isinstance(item.get('id'), str)})
            if not models:
                raise HTTPException(502, '服务未返回可用的模型列表')
            return {'models': models}
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(502, '无法获取模型列表，请检查接口地址和网络')

@app.post('/api/extract')
async def extract(data: RepoRequest):
    owner, name = repo_parts(data.repo)
    config = settings()
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'OpenSourceLibrary'}
    if config.get('github_token'):
        headers['Authorization'] = 'Bearer ' + config['github_token']
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(f'https://api.github.com/repos/{owner}/{name}', headers=headers)
            if response.status_code != 200:
                if response.status_code == 401:
                    raise HTTPException(401, 'GitHub Token 无效或已过期，请检查设置')
                if response.status_code == 403:
                    remaining = response.headers.get('x-ratelimit-remaining')
                    detail = 'GitHub API 请求额度已用完，请稍后重试或检查 Token' if remaining == '0' else 'GitHub 拒绝访问，请检查 Token 权限或仓库可见性'
                    raise HTTPException(403, detail)
                raise HTTPException(response.status_code if response.status_code == 404 else 502, f'GitHub 获取失败（HTTP {response.status_code}），可手动填写')
            info = response.json()
            readme_response = await client.get(f'https://api.github.com/repos/{owner}/{name}/readme', headers=headers)
            readme = ''
            if readme_response.status_code == 200:
                try:
                    readme = base64.b64decode(readme_response.json().get('content', '')).decode('utf-8', errors='replace')[:40000]
                except (ValueError, TypeError):
                    pass
            text = (info.get('description') or '') + ' ' + ' '.join(info.get('topics', [])) + ' ' + readme[:10000]
            platforms = [p for p in ('Windows', 'macOS', 'Linux', 'Android', 'iOS') if re.search(r'\b' + re.escape(p) + r'\b', text, re.I)]
            if re.search(r'\b(web app|web-based|browser)\b', text, re.I):
                platforms.append('Web')
            candidates = []
            class ImageParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.sources = []
                def handle_starttag(self, tag, attrs):
                    if tag.lower() == 'img':
                        source = dict(attrs).get('src')
                        if source:
                            self.sources.append(source)
            parser = ImageParser()
            parser.feed(readme)
            sources = [m.group(1).strip('<>') for m in re.finditer(r'!\[[^\]]*\]\(([^\s)]+)', readme)] + parser.sources
            for source in sources:
                if re.search(r'badge|shields\.io', source, re.I):
                    continue
                url = urljoin(f'https://raw.githubusercontent.com/{owner}/{name}/{info["default_branch"]}/', source)
                if urlparse(url).scheme == 'https' and url not in candidates:
                    candidates.append(url)
            result = {'repo': normalize_repo(data.repo), 'name': info['name'], 'description': info.get('description') or '', 'category': '', 'platforms': platforms or ['待确认'], 'tags': info.get('topics', []), 'stars': info.get('stargazers_count'), 'license': (info.get('license') or {}).get('spdx_id') or '', 'updated_at': info.get('updated_at') or '', 'screenshot': '', 'published': False, 'candidates': candidates[:100], 'icon_candidate': next((url for url in candidates if re.search(r'(^|[/_.-])(icon|logo)([/_.-]|$)', urlparse(url).path, re.I)), ''), 'warning': ''}
            lower = text.lower()
            rules = {'开发工具': ('developer', 'development', 'programming', 'code editor'), '设计创作': ('drawing', 'design tool', 'whiteboard'), '媒体工具': ('photo', 'video', 'music', 'media'), '效率工具': ('notes', 'productivity', 'task management')}
            available = {entry['name'] for entry in categories()}
            for category, words in rules.items():
                if category in available and any(word in lower for word in words):
                    result['category'] = category
                    break
            if config.get('ai_enabled') == 'true' and config.get('ai_url') and config.get('ai_model') and config.get('ai_key'):
                payload = None
                ai = None
                request_body = None
                try:
                    names = [x['name'] for x in categories()]
                    request_body = {'model': config['ai_model'], 'messages': [{'role':'system','content':'根据开源项目信息返回 JSON 对象：description（中文简介）、category（从给定分类中选择）、platforms（数组，不确定用待确认）、tags（数组）。不要编造。'}, {'role':'user','content':json.dumps({'categories': names, 'description':info.get('description'), 'topics':info.get('topics'), 'readme':readme[:16000]}, ensure_ascii=False)}], 'temperature':0.2}
                    ai = await client.post(config['ai_url'].rstrip('/') + '/chat/completions', headers={'Authorization': 'Bearer ' + config['ai_key']}, json=request_body)
                    ai.raise_for_status()
                    payload = ai.json()
                    content = payload['choices'][0]['message']['content'].strip()
                    content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content)
                    generated = json.loads(content)
                    for key in ('description', 'category', 'platforms', 'tags'):
                        if key in generated and isinstance(generated[key], type(result[key])):
                            result[key] = generated[key]
                    record_ai_usage(result['repo'], config['ai_model'], '成功', payload.get('usage'), request_body, ai.text)
                    if result['category'] not in names:
                        result['category'] = ''
                except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                    record_ai_usage(result['repo'], config['ai_model'], '失败', payload.get('usage') if isinstance(payload, dict) else None, request_body, ai.text if ai is not None else '请求失败，未收到响应')
                    result['warning'] = 'AI 整理失败，已保留基础提取结果'
            return result
    except httpx.TimeoutException:
        raise HTTPException(504, '连接 GitHub 超时，请检查容器网络、代理和 DNS')
    except httpx.ConnectError as exc:
        reason = str(exc).lower()
        if 'certificate' in reason or 'ssl' in reason:
            raise HTTPException(502, 'GitHub TLS 证书验证失败，请检查系统时间、代理和证书')
        if 'name or service' in reason or 'resolve' in reason or 'getaddrinfo' in reason:
            raise HTTPException(502, '无法解析 GitHub 域名，请检查容器 DNS')
        raise HTTPException(502, '无法连接 GitHub，请检查容器网络和代理设置')
    except httpx.HTTPError:
        raise HTTPException(502, 'GitHub 网络请求失败，请检查容器网络和代理设置')

@app.get('/api/backup')
def export_backup():
    with db() as conn:
        projects_data = [row_project(row) for row in conn.execute('SELECT * FROM projects ORDER BY id')]
        categories_data = [row['name'] for row in conn.execute('SELECT name FROM categories ORDER BY rowid')]
    manifest = {'version': 1, 'projects': projects_data, 'categories': categories_data}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('backup.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        paths = {p.get(field, '') for p in projects_data for field in ('icon', 'screenshot')}
        for url in paths:
            name = url.removeprefix('/images/')
            if url.startswith('/images/') and re.fullmatch(r'[a-f0-9]{32}\.(png|jpg|gif|webp|svg|ico)', name):
                file = IMAGES / name
                if file.is_file():
                    archive.write(file, 'images/' + name)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="opensource-library-backup.zip"'})

@app.post('/api/restore')
async def restore_backup(file: UploadFile = File(...)):
    raw = await file.read(100 * 1024 * 1024 + 1)
    if len(raw) > 100 * 1024 * 1024:
        raise HTTPException(400, '备份文件超过 100 MB')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > 5000 or sum(i.file_size for i in infos) > 200 * 1024 * 1024 or len({i.filename for i in infos}) != len(infos):
                raise ValueError('备份内容过大或包含重复文件')
            if any(i.file_size > 50 * 1024 * 1024 for i in infos):
                raise ValueError('备份中存在过大的文件')
            manifest = json.loads(archive.read('backup.json'))
            if manifest.get('version') != 1 or not isinstance(manifest.get('projects'), list) or not isinstance(manifest.get('categories'), list):
                raise ValueError('不支持的备份格式')
            cats = manifest['categories']
            if any(not isinstance(c, str) or not c.strip() or len(c) > 100 for c in cats) or len(set(cats)) != len(cats):
                raise ValueError('分类数据无效')
            projects_data = [Project.model_validate(item) for item in manifest['projects']]
            images = {}
            for project in projects_data:
                project.repo = normalize_repo(project.repo)
                for field in ('icon', 'screenshot'):
                    url = getattr(project, field)
                    if url.startswith('/images/') and url not in images:
                        name = url.removeprefix('/images/')
                        if not re.fullmatch(r'[a-f0-9]{32}\.(png|jpg|gif|webp|svg|ico)', name):
                            raise ValueError('图片路径无效')
                        images[url] = archive.read('images/' + name)
            if len({p.repo for p in projects_data}) != len(projects_data):
                raise ValueError('备份包含重复仓库')
            mapped = {url: save_image(content, max_size=50 * 1024 * 1024)['url'] for url, content in images.items()}
            with db() as conn:
                conn.execute('DELETE FROM projects')
                conn.execute('DELETE FROM categories')
                conn.executemany('INSERT INTO categories VALUES (?)', [(name,) for name in cats])
                for project in projects_data:
                    values = project.model_dump()
                    for field in ('icon', 'screenshot'):
                        values[field] = mapped.get(values[field], values[field])
                    for field in ('platforms', 'tags'):
                        values[field] = json.dumps(values[field], ensure_ascii=False)
                    conn.execute('INSERT INTO projects (' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', list(values.values()))
            return {'projects': len(projects_data), 'categories': len(cats)}
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError, sqlite3.IntegrityError) as exc:
        raise HTTPException(400, '备份文件无效或不完整：' + str(exc))

@app.post('/api/download-image')
async def download_image(image: ImageRequest):
    parsed = urlparse(image.url)
    allowed = ('raw.githubusercontent.com', 'github.com', 'user-images.githubusercontent.com', 'private-user-images.githubusercontent.com', 'daeuniverse.org', 'cdn.nodeimage.com')
    if parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.port not in (None, 443):
        raise HTTPException(400, '该图片来源暂不支持自动保存，请手动上传')
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            target = image.url
            if parsed.hostname == 'github.com' and re.fullmatch(r'/user-attachments/assets/[0-9a-fA-F-]+', parsed.path):
                redirect = await client.get(target)
                if redirect.status_code in (301, 302, 303, 307, 308):
                    target = urljoin(target, redirect.headers.get('location', ''))
                    destination = urlparse(target)
                    if destination.scheme != 'https' or destination.hostname != 'github-production-user-asset-6210df.s3.amazonaws.com' or destination.port not in (None, 443):
                        raise HTTPException(400, '图片跳转地址不受支持')
            async with client.stream('GET', target) as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 50 * 1024 * 1024:
                        raise HTTPException(400, '图片不能超过 50 MB')
        return save_image(bytes(data), max_size=50 * 1024 * 1024)
    except httpx.HTTPError:
        raise HTTPException(502, '图片下载失败，请尝试手动上传')

def save_image(data: bytes, max_size: int = 5 * 1024 * 1024):
    signatures = [(b'\x89PNG\r\n\x1a\n', '.png'), (b'\xff\xd8\xff', '.jpg'), (b'GIF87a', '.gif'), (b'GIF89a', '.gif'), (b'RIFF', '.webp'), (b'\x00\x00\x01\x00', '.ico')]
    suffix = next ( (ext for magic, ext in signatures if data.startswith(magic) and (ext != '.webp' or data[8:12] == b'WEBP')), None)
    if len(data) > max_size:
        raise HTTPException(400, f'图片超过 {max_size // (1024 * 1024)} MB，请选择更小的图片')
    if not suffix:
        try:
            if re.search(br'<!\s*(?:DOCTYPE|ENTITY)\b', data, re.I) or len(data) > max_size:
                raise ValueError('unsupported declaration')
            root = ET.fromstring(data)
            allowed_tags = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'defs', 'linearGradient', 'radialGradient', 'stop', 'clipPath', 'mask', 'title', 'desc', 'use', 'symbol', 'pattern', 'text', 'tspan'}
            allowed_attrs = {'viewBox', 'width', 'height', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry', 'd', 'points', 'fill', 'fill-opacity', 'fill-rule', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-opacity', 'stroke-dasharray', 'stroke-dashoffset', 'stroke-miterlimit', 'opacity', 'transform', 'id', 'offset', 'stop-color', 'stop-opacity', 'clip-path', 'clip-rule', 'mask', 'gradientUnits', 'gradientTransform', 'spreadMethod', 'preserveAspectRatio', 'version', 'href', 'font-size', 'font-family', 'font-weight', 'text-anchor', 'dominant-baseline', 'patternUnits', 'patternTransform'}
            svg_ns = '{http://www.w3.org/2000/svg}'
            if root.tag != svg_ns + 'svg':
                raise ValueError('not svg')
            def safe_value(name, value):
                value = value.strip()
                if name == 'href':
                    return bool(re.fullmatch(r'#[A-Za-z0-9_.:-]+', value))
                if any(x in value.lower() for x in ('javascript:', 'data:', 'http:', 'https:', '@import', 'expression', '\\')):
                    return False
                return 'url(' not in value.lower() or bool(re.fullmatch(r'url\(#[A-Za-z0-9_.:-]+\)', value))
            def sanitize(element):
                for child in list(element):
                    if not isinstance(child.tag, str) or not child.tag.startswith(svg_ns) or child.tag[len(svg_ns):] not in allowed_tags:
                        element.remove(child)
                    else:
                        sanitize(child)
                attrs = dict(element.attrib)
                element.attrib.clear()
                style = attrs.pop('style', '')
                for declaration in style.split(';'):
                    if ':' in declaration:
                        name, value = (part.strip() for part in declaration.split(':', 1))
                        if name in allowed_attrs and safe_value(name, value):
                            element.set(name, value)
                for name, value in attrs.items():
                    if name == '{http://www.w3.org/1999/xlink}href':
                        name = 'href'
                    if name in allowed_attrs and safe_value(name, value):
                        element.set(name, value)
            sanitize(root)
            data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            suffix = '.svg'
        except (ET.ParseError, ValueError):
            raise HTTPException(400, '图片格式不受支持，或 SVG 含有不支持的内容；请尝试上传 PNG 或简化的 SVG')
    filename = uuid.uuid4().hex + suffix
    (IMAGES / filename).write_bytes(data)
    return {'url': '/images/' + filename}

@app.post('/api/upload')
async def upload(file: UploadFile = File(...)):
    data = await file.read(5 * 1024 * 1024 + 1)
    return save_image(data)

DIST = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
if DIST.exists():
    app.mount('/', StaticFiles(directory=DIST, html=True), name='frontend')
