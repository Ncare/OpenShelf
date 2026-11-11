import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { App as AntApp, Button, Card, ConfigProvider, Empty, Form, Input, InputNumber, Layout, Menu, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Tooltip, Typography, Upload } from 'antd';
import { PlusOutlined, SettingOutlined, AppstoreOutlined, SearchOutlined, UploadOutlined, EditOutlined, ReloadOutlined, EyeOutlined, EyeInvisibleOutlined, DeleteOutlined } from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';
import './style.css';

type Project = { id?: number; repo: string; name: string; description: string; category: string; platforms: string[]; tags: string[]; screenshot: string; icon: string; stars: number | null; license: string; updated_at: string; published: boolean; candidates?: string[]; warning?: string };
type Category = { name: string; count: number };
const blank: Project = { repo: '', name: '', description: '', category: '', platforms: ['待确认'], tags: [], screenshot: '', icon: '', stars: null, license: '', updated_at: '', published: false };
const platformOptions = ['Windows', 'macOS', 'Linux', 'Android', 'iOS', 'Web', '待确认'].map(value => ({ value }));
async function api(path: string, options: RequestInit = {}) {
    const response = await fetch('/api' + path, { ...options, headers: options.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '请求失败');
    return data;
}
const send = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

function formatUsageBody(value: string | null): string {
    if (!value) return '';
    try {
        return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
        return value;
    }
}

function Main() {
    const { message, modal } = AntApp.useApp();
    const [background, setBackground] = useState(() => localStorage.getItem('library-background') || 'sage');
    const [admin, setAdmin] = useState(location.hash.startsWith('#admin'));
    const [page, setPage] = useState('projects');
    const [projects, setProjects] = useState<Project[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [query, setQuery] = useState('');
    const [category, setCategory] = useState('');
    const [platform, setPlatform] = useState('');
    const [status, setStatus] = useState('all');
    const [addStep, setAddStep] = useState<'link' | 'details'>('link');
    const [editing, setEditing] = useState<Project | null>(null);
    const [isOpen, setOpen] = useState(false);
    const [repo, setRepo] = useState('');
    const [loading, setLoading] = useState(false);
    const candidateStrip = useRef<HTMLDivElement>(null);
    const [candidates, setCandidates] = useState<string[]>([]);
    const [imageTarget, setImageTarget] = useState<'icon' | 'screenshot'>('icon');
    const [settings, setSettings] = useState<any>({});
    const [usageDetail, setUsageDetail] = useState<any>(null);
    const [usage, setUsage] = useState<any>({summary:{},records:[]});
    const [keyVisible, setKeyVisible] = useState(false);
    const [models, setModels] = useState<string[]>([]);
    const [modelsLoading, setModelsLoading] = useState(false);
    const [form] = Form.useForm();
    const [selectedImages, setSelectedImages] = useState<Record<string, {source:string, saved:string}>>({});
    const iconValue = Form.useWatch('icon', form);
    const screenshotValue = Form.useWatch('screenshot', form);
    const [settingsForm] = Form.useForm();
    const [categoryForm] = Form.useForm();
    const [categoryOpen, setCategoryOpen] = useState(false);
    const [categoryName, setCategoryName] = useState('');
    const [detail, setDetail] = useState<Project | null>(null);
    const load = async () => {
        try {
            const [p, c, s] = await Promise.all([api('/projects' + (admin ? '' : '?published=true')), api('/categories'), admin ? api('/settings') : Promise.resolve({})]);
            setProjects(p); setCategories(c); setSettings(s); settingsForm.setFieldsValue(s);
            if (admin) setUsage(await api('/ai/usage'));
        } catch (e) { message.error((e as Error).message); }
    };
    useEffect(() => { load(); }, [admin]);
    useEffect(() => {
        const listener = () => setAdmin(location.hash.startsWith('#admin'));
        window.addEventListener('hashchange', listener);
        return () => window.removeEventListener('hashchange', listener);
    }, []);
    const enter = () => { location.hash = 'admin'; setAdmin(true); };
    const openProject = (project?: Project) => {
        setSelectedImages({}); setEditing(project || null); setAddStep(project ? 'details' : 'link'); setRepo(project?.repo || ''); setCandidates([]);
        form.resetFields(); form.setFieldsValue(project || blank); setOpen(true);
    };
    const extract = async () => {
        setLoading(true);
        try {
            const data = await api('/extract', send('POST', { repo }));
            form.setFieldsValue(data); setCandidates(data.candidates || []); setAddStep('details');
            if (data.icon_candidate) {
                try {
                    const image = await api('/download-image', send('POST', {url: data.icon_candidate}));
                    form.setFieldValue('icon', image.url);
                    setSelectedImages(current => ({...current, icon:{source:data.icon_candidate,saved:image.url}}));
                } catch { message.warning('发现可能的图标，但自动保存失败，可从候选图片手动选择'); }
            }
            if (data.warning) message.warning(data.warning); else message.success('已提取，请检查并补充信息');
        } catch (e) { form.setFieldValue('repo', repo); message.error((e as Error).message); }
        finally { setLoading(false); }
    };
    const save = async () => {
        try {
            const values = await form.validateFields();
            await api('/projects' + (editing?.id ? '/' + editing.id : ''), send(editing ? 'PUT' : 'POST', { ...blank, ...editing, ...values }));
            setOpen(false); message.success('已保存'); await load();
        } catch (e: any) { if (e.message) message.error(e.message); }
    };
    const changePublish = async (p: Project) => {
        try { await api('/projects/' + p.id, send('PUT', { ...p, published: !p.published })); message.success(p.published ? '已取消发布' : '已发布'); await load(); }
        catch (e) { message.error((e as Error).message); }
    };
    const refresh = async (p: Project) => {
        try {
            message.loading({content:'正在刷新仓库信息', key:'refresh'});
            const data = await api('/extract', send('POST', {repo:p.repo}));
            await api('/projects/' + p.id, send('PUT', {...p, stars:data.stars, license:data.license, updated_at:data.updated_at}));
            message.success({content:'仓库信息已刷新', key:'refresh'}); await load();
        } catch (e) { message.error({content:(e as Error).message, key:'refresh'}); }
    };
    const remove = async (id: number) => {
        try { await api('/projects/' + id, send('DELETE')); message.success('已删除'); await load(); }
        catch (e) { message.error((e as Error).message); }
    };
    const saveCategory = async () => {
        try {
            const values = await categoryForm.validateFields();
            await api('/categories' + (categoryName ? '/' + encodeURIComponent(categoryName) : ''), send(categoryName ? 'PUT' : 'POST', values));
            setCategoryOpen(false); message.success('分类已保存'); await load();
        } catch (e: any) { if (e.message) message.error(e.message); }
    };
    const upload = async (file: File, target: 'icon' | 'screenshot' = 'screenshot') => {
        const data = new FormData(); data.append('file', file);
        try { const result = await api('/upload', { method: 'POST', body: data }); form.setFieldValue(target, result.url); setSelectedImages(current => {const next={...current};delete next[target];return next}); message.success('图片已上传'); }
        catch (e) { message.error((e as Error).message); }
        return false;
    };
    const list = projects.filter(p => (!category || p.category === category) && (!platform || p.platforms.includes(platform)) && (p.name + p.description + p.tags.join(' ')).toLowerCase().includes(query.toLowerCase()));
    const columns = [
        { title: '软件', dataIndex: 'name', render: (_: unknown, p: Project) => <div><strong>{p.name}</strong><div className="muted ellipsis">{p.description}</div></div> },
        { title: '分类', dataIndex: 'category', width: 160, render: (v: string) => <span style={{whiteSpace:'nowrap'}}>{v || '待分类'}</span> },
        { title: '平台', dataIndex: 'platforms', filters: platformOptions.map(option => ({text: option.value, value: option.value})), onFilter: (value: React.Key | boolean, p: Project) => p.platforms.includes(String(value)), render: (v: string[]) => v.join('、') },
        { title: '状态', dataIndex: 'published', filters: [{text: '已发布', value: 'published'}, {text: '未发布', value: 'draft'}], onFilter: (value: React.Key | boolean, p: Project) => p.published === (value === 'published'), render: (_: unknown, p: Project) => <Tag color={p.published ? 'success' : 'default'}>{p.published ? '已发布' : '未发布'}</Tag> },
        { title: '操作', render: (_: unknown, p: Project) => <Space size={2}><Tooltip title="编辑"><Button type="text" aria-label="编辑" icon={<EditOutlined />} onClick={() => openProject(p)} /></Tooltip><Tooltip title="刷新仓库信息"><Button type="text" aria-label="刷新仓库信息" icon={<ReloadOutlined />} onClick={() => refresh(p)} /></Tooltip><Tooltip title={p.published ? '取消发布' : '发布'}><Button type="text" aria-label={p.published ? '取消发布' : '发布'} icon={p.published ? <EyeInvisibleOutlined /> : <EyeOutlined />} onClick={() => changePublish(p)} /></Tooltip><Popconfirm title="确定删除这条软件记录？" onConfirm={() => remove(p.id!)} okText="删除" cancelText="取消"><Tooltip title="删除"><Button type="text" danger aria-label="删除" icon={<DeleteOutlined />} /></Tooltip></Popconfirm></Space> }
    ];
    return <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#356d49', borderRadius: 9, fontFamily: 'system-ui, Microsoft YaHei, sans-serif' } }}>
        {!admin ? <main className={`front background-${background}`}><header className="front-header"><strong>◈ 开源集</strong><Space><div className="theme-switch" role="group" aria-label="切换背景主题">{[{value:'sage',label:'柔和绿'},{value:'cloud',label:'云白'},{value:'blue',label:'雾蓝'},{value:'sand',label:'暖沙'}].map(theme => <button key={theme.value} type="button" className={'theme-dot theme-dot-' + theme.value + (background === theme.value ? ' selected' : '')} title={theme.label} aria-label={theme.label} aria-pressed={background === theme.value} onClick={() => {setBackground(theme.value); localStorage.setItem('library-background', theme.value);}} />)}</div><Button type="text" onClick={enter}>管理后台 ↗</Button></Space></header>
            <div className="filters glass"><Input allowClear prefix={<SearchOutlined />} placeholder="搜索软件名称、功能或标签" value={query} onChange={e => setQuery(e.target.value)} /><Select allowClear placeholder="全部分类" value={category || undefined} onChange={v => setCategory(v || '')} options={categories.map(c => ({ value: c.name }))} /><Select allowClear placeholder="全部平台" value={platform || undefined} onChange={v => setPlatform(v || '')} options={platformOptions} /></div>
            <div className="grid">{list.map(p => <Card key={p.id} className="project-card glass" hoverable onClick={() => setDetail(p)} cover={p.screenshot ? <img className="cover" src={p.screenshot} /> : <div className="cover cover-empty" aria-label="暂无截图" />}><div className="card-heading">{p.icon ? <img className="project-icon icon-image" src={p.icon} alt="" onError={e => { e.currentTarget.style.display = 'none'; e.currentTarget.nextElementSibling?.classList.remove('icon-fallback-hidden'); }} /> : null}<span className={'project-icon ' + (p.icon ? 'icon-fallback-hidden' : '')}>{p.name.slice(0,2).toUpperCase()}</span><div className="card-name">{p.name}<span className="card-category">{p.category || '开源软件'}</span></div></div><p className="description">{p.description || '暂无简介'}</p><Space size={[4,4]} wrap>{p.platforms.filter(Boolean).map(t => <Tag key={t}>{t}</Tag>)}</Space><div className="card-foot"><span>☆ {p.stars ?? '—'} · GitHub</span><span>查看详情 ↗</span></div></Card>)}</div>{!list.length && <Empty description="暂无匹配的软件" />}
        </main> : <Layout className="admin"><Layout.Sider breakpoint="md" collapsedWidth="0" className="sidebar"><div className="brand">◈ 开源集 <small>OPEN SOURCE LIBRARY</small></div><Menu theme="dark" selectedKeys={[page]} onClick={e => setPage(e.key)} items={[{key:'projects',icon:<AppstoreOutlined />,label:'软件管理'},{key:'settings',icon:<SettingOutlined />,label:'设置'}]} /><div className="sidefoot">你的私人开源收藏</div></Layout.Sider><Layout.Content className="admin-content"><div className="admin-crumb">管理后台 / {page === 'projects' ? '软件管理' : '设置'}</div>{page === 'projects' ? <><div className="section-heading"><h2>全部项目</h2><Button type="primary" icon={<PlusOutlined />} onClick={() => openProject()}>添加软件</Button></div><Table rowKey="id" columns={columns} dataSource={list} scroll={{ x: 850 }} pagination={{ pageSize: 10 }} /></> : <div className="settings-grid">
            <Card title="分类管理" extra={<Button icon={<PlusOutlined />} onClick={() => { setCategoryName(''); categoryForm.resetFields(); setCategoryOpen(true); }}>新增分类</Button>}><Table size="small" rowKey="name" pagination={false} dataSource={categories} columns={[{title:'分类名称',dataIndex:'name'},{title:'软件数量',dataIndex:'count'},{title:'操作',render:(_,c:Category)=><Space><Tooltip title="编辑分类"><Button type="text" aria-label="编辑分类" icon={<EditOutlined />} onClick={()=>{setCategoryName(c.name);categoryForm.setFieldsValue({name:c.name});setCategoryOpen(true);}} /></Tooltip><Popconfirm title={c.count ? `该分类有 ${c.count} 个软件，请先调整分类` : '确定删除该分类？'} disabled={!!c.count} onConfirm={async()=>{try{await api('/categories/'+encodeURIComponent(c.name),send('DELETE'));await load();}catch(e){message.error((e as Error).message)}}}><Tooltip title={c.count ? '请先调整该分类下的软件' : '删除分类'}><span><Button type="text" danger aria-label="删除分类" icon={<DeleteOutlined />} disabled={!!c.count} /></span></Tooltip></Popconfirm></Space>}]} /></Card>
            <Card className="settings-card" title="AI 辅助整理"><p className="muted">启用后，仓库信息将发送至配置的 AI 服务。未启用时使用基础规则。</p><Form form={settingsForm} layout="vertical" onFinish={async values=>{try{if(settings.has_ai_key && values.ai_url?.replace(/\/$/,'') !== settings.ai_url?.replace(/\/$/,'') && !values.ai_key){message.warning('更换接口地址时，请输入对应服务的 API Key');return;}await api('/settings',send('PUT',values));message.success('设置已保存');await load();}catch(e){message.error((e as Error).message)}}}><Form.Item name="ai_enabled" label="启用 AI" valuePropName="checked"><Switch /></Form.Item><Form.Item label="常用服务"><Select placeholder="选择服务，自动填写接口地址" onChange={(value: string) => { settingsForm.setFieldValue('ai_url', value); settingsForm.setFieldValue('ai_model', ''); settingsForm.setFieldValue('ai_key', ''); setModels([]); }} options={[{label:'DeepSeek',value:'https://api.deepseek.com'},{label:'OpenAI',value:'https://api.openai.com/v1'}]} /><div className="muted">选择后输入对应的 API Key 并获取模型列表；也可直接输入其他兼容接口。</div></Form.Item><Form.Item name="ai_url" label="接口地址"><Input placeholder="https://api.example.com/v1" /></Form.Item><Form.Item name="ai_key" label="API Key"><Input.Password placeholder={settings.has_ai_key ? '已设置，点击眼睛查看' : '输入 API Key'} visibilityToggle={{visible:keyVisible,onVisibleChange:async visible=>{if(visible && settings.has_ai_key && !settingsForm.getFieldValue('ai_key')){try{const result=await api('/settings/ai-key');settingsForm.setFieldValue('ai_key',result.ai_key)}catch(e){message.error((e as Error).message);return}}setKeyVisible(visible)}}} /></Form.Item><Button loading={modelsLoading} onClick={async()=>{setModelsLoading(true);try{const result=await api('/ai/models',send('POST',{ai_url:settingsForm.getFieldValue('ai_url')||'',ai_key:settingsForm.getFieldValue('ai_key')||''}));setModels(result.models);message.success('模型列表已获取');}catch(e){message.error((e as Error).message)}finally{setModelsLoading(false)}}}>获取模型列表</Button><Form.Item name="ai_model" label="选择模型" style={{marginTop:16}} rules={[({getFieldValue})=>({validator(_,value){return !getFieldValue('ai_enabled') || value ? Promise.resolve() : Promise.reject(new Error('请选择模型'))}})]}><Select showSearch placeholder="先获取模型列表，再选择模型" options={[...new Set([...models, settings.ai_model].filter(Boolean))].map(value=>({value}))} /></Form.Item><Form.Item name="github_token" label="GitHub Token（可选）"><Input.Password placeholder={settings.has_github_token ? '已设置，留空保持不变' : '可选填写'} /></Form.Item><Button htmlType="submit" type="primary">保存设置</Button></Form></Card>
            <Card className="backup-card" title="备份与恢复"><p className="muted">备份包含软件、分类、图标和截图，不包含 AI 或 GitHub 密钥及 AI 使用记录。恢复会替换当前软件与分类，建议先备份当前数据。</p><Space wrap><Button href="/api/backup">下载备份</Button><Upload accept=".zip,application/zip" showUploadList={false} beforeUpload={file=>{modal.confirm({title:'恢复备份？',content:'恢复将替换当前的软件和分类。设置及 AI 使用记录保留。请确认已备份当前数据。',okText:'确认恢复',okButtonProps:{danger:true},cancelText:'取消',onOk:async()=>{try{const data=new FormData();data.append('file',file);const result=await api('/restore',{method:'POST',body:data});message.success(`已恢复 ${result.projects} 个软件和 ${result.categories} 个分类`);await load()}catch(e){message.error((e as Error).message)}}});return false}}><Button>恢复备份</Button></Upload></Space></Card>
            <Card className="usage-card" title="AI 使用记录" extra={<Button onClick={async()=>{try{setUsage(await api('/ai/usage'))}catch(e){message.error((e as Error).message)}}}>刷新</Button>}><div className="usage-summary"><span>调用次数 <strong>{usage.summary.calls || 0}</strong></span><span>输入 Token <strong>{usage.summary.input_tokens || 0}</strong></span><span>输出 Token <strong>{usage.summary.output_tokens || 0}</strong></span><span>总 Token <strong>{usage.summary.total_tokens || 0}</strong></span></div><p className="muted">Token 以服务商返回的数据为准；未返回用量的调用不计入 Token 汇总。暂不估算费用。</p><Table size="small" rowKey="id" dataSource={usage.records} pagination={{pageSize: 8, hideOnSinglePage:true}} scroll={{x:700}} columns={[{title:'时间',dataIndex:'created_at',render:(value:string)=>new Date(value.replace(' ','T')+'Z').toLocaleString()},{title:'任务',dataIndex:'task'},{title:'项目',dataIndex:'repo',render:(value:string)=>value.replace('https://github.com/','')},{title:'模型',dataIndex:'model'},{title:'结果',dataIndex:'status'},{title:'Token',dataIndex:'total_tokens',render:(value:number|null)=>value ?? '未提供'},{title:'详情',render:(_:unknown,row:any)=><Button type="link" onClick={async()=>{try{setUsageDetail(await api('/ai/usage/'+row.id))}catch(e){message.error((e as Error).message)}}}>查看</Button>}]} /></Card>
        </div>}</Layout.Content></Layout>}
        <Modal title={editing ? '编辑软件' : addStep === 'link' ? '添加软件 · 输入链接' : '添加软件 · 确认信息'} open={isOpen} onCancel={() => setOpen(false)} onOk={save} footer={addStep === 'link' && !editing ? null : undefined} okText="确认保存" cancelText="取消" width={720} className="project-modal" centered destroyOnHidden>{!editing && addStep === 'link' && <p className="muted">粘贴 GitHub 仓库链接，获取软件信息。</p>}{!editing && addStep === 'link' && <Space.Compact style={{width:'100%',margin:'12px 0 20px'}}><Input value={repo} onChange={e=>{setRepo(e.target.value);form.setFieldValue('repo',e.target.value)}} placeholder="https://github.com/owner/repository" /><Button type="primary" loading={loading} onClick={extract}>提取信息</Button></Space.Compact>}{!editing && addStep === 'link' && <Button type="link" onClick={()=>{form.setFieldValue('repo',repo);setAddStep('details')}}>手动填写信息</Button>}<Form style={{display: addStep === 'link' && !editing ? 'none' : undefined}} form={form} layout="vertical" initialValues={blank}><Form.Item name="repo" label="GitHub 仓库链接" hidden={!editing} rules={[{required:true, message:'请填写仓库链接'}]}><Input disabled={!!editing} /></Form.Item><Form.Item name="name" label="软件名称" rules={[{required:true,message:'请填写软件名称'}]}><Input /></Form.Item><Form.Item name="description" label="中文功能简介"><Input.TextArea rows={3} /></Form.Item><div className="project-form-grid"><Form.Item name="category" label="分类"><Select allowClear options={categories.map(c=>({value:c.name}))} /></Form.Item><Form.Item name="platforms" label="支持平台"><Select mode="multiple" maxTagCount="responsive" options={platformOptions} /></Form.Item><Form.Item name="tags" hidden><Select mode="tags" /></Form.Item></div><Form.Item label="应用图标"><Space.Compact style={{width:'100%'}}><Form.Item name="icon" noStyle><Input placeholder="图标地址，或上传图片" /></Form.Item><Upload accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml,image/x-icon,image/vnd.microsoft.icon" showUploadList={false} beforeUpload={file => upload(file, 'icon')}><Button icon={<UploadOutlined />}>上传图标</Button></Upload></Space.Compact>{iconValue && <div className="selected-preview"><img src={iconValue} alt="当前应用图标" /><span>当前图标</span><Button type="link" danger onClick={()=>{form.setFieldValue('icon','');setSelectedImages(current=>{const next={...current};delete next.icon;return next})}}>移除</Button></div>}</Form.Item><Form.Item label="软件截图"><Space.Compact style={{width:'100%'}}><Form.Item name="screenshot" noStyle><Input placeholder="图片地址，或上传图片" /></Form.Item><Upload accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml,image/x-icon,image/vnd.microsoft.icon" showUploadList={false} beforeUpload={file => upload(file, 'screenshot')}><Button icon={<UploadOutlined />}>上传图片</Button></Upload></Space.Compact>{screenshotValue && <div className="selected-preview"><img src={screenshotValue} alt="当前软件截图" /><span>当前截图</span><Button type="link" danger onClick={()=>{form.setFieldValue('screenshot','');setSelectedImages(current=>{const next={...current};delete next.screenshot;return next})}}>移除</Button></div>}</Form.Item><div className="candidate-controls">{editing && <Button loading={loading} onClick={async()=>{setLoading(true);try{const data=await api('/extract',send('POST',{repo:editing.repo}));setCandidates(data.candidates || []);message.info(data.candidates?.length ? '已获取候选图片，请点击选择' : '没有找到候选图片');}catch(e){message.error((e as Error).message)}finally{setLoading(false)}}}>重新获取候选图片</Button>}{candidates.length > 0 && <><span className="muted">选择用途后点击图片</span><Select value={imageTarget} onChange={setImageTarget} options={[{value:'icon',label:'用作应用图标'},{value:'screenshot',label:'用作软件截图'}]} /></>}</div>{candidates.length > 0 && <><div className="candidate-carousel"><Button aria-label="向左查看候选图片" onClick={()=>candidateStrip.current?.scrollBy({left:-330,behavior:'smooth'})}>‹</Button><div className="candidates" ref={candidateStrip}>{candidates.map(url=>{const isIcon=selectedImages.icon?.source===url && selectedImages.icon.saved===iconValue;const isScreenshot=selectedImages.screenshot?.source===url && selectedImages.screenshot.saved===screenshotValue;return <button type="button" key={url} className={'candidate-item'+(isIcon||isScreenshot?' selected':'')} aria-label="选择候选图片" onClick={async()=>{try{const image=await api('/download-image',send('POST',{url}));form.setFieldValue(imageTarget,image.url);setSelectedImages(current=>({...current,[imageTarget]:{source:url,saved:image.url}}));message.success('图片已选择');}catch(e){message.error((e as Error).message)}}}><img src={url} alt="候选图片" />{(isIcon||isScreenshot)&&<span className="candidate-badge">{isIcon?'图标':''}{isIcon&&isScreenshot?' / ':''}{isScreenshot?'截图':''}</span>}</button>})}</div><Button aria-label="向右查看候选图片" onClick={()=>candidateStrip.current?.scrollBy({left:330,behavior:'smooth'})}>›</Button></div></>}<div className="meta-fields"><Form.Item name="stars" label="Star 数"><InputNumber min={0} /></Form.Item><Form.Item name="license" label="许可证"><Input /></Form.Item><Form.Item name="updated_at" label="仓库更新时间"><Input /></Form.Item></div></Form></Modal>
        <Modal title="AI 调用详情" open={!!usageDetail} onCancel={()=>setUsageDetail(null)} footer={<Button onClick={()=>setUsageDetail(null)}>关闭</Button>} width={800}>{usageDetail && <><p className="muted">{usageDetail.task} · {usageDetail.model} · {usageDetail.status}</p><h4>请求内容</h4><pre className="usage-json">{formatUsageBody(usageDetail.request_body) || '历史记录未保存请求内容'}</pre><h4>响应内容</h4><pre className="usage-json">{formatUsageBody(usageDetail.response_body) || '历史记录未保存响应内容'}</pre><p className="muted">请求和响应保存在本地数据库中，不包含授权请求头。</p></>}</Modal>
        <Modal title={categoryName ? '编辑分类' : '新增分类'} open={categoryOpen} onCancel={()=>setCategoryOpen(false)} onOk={saveCategory} okText="保存" cancelText="取消"><Form form={categoryForm} layout="vertical"><Form.Item name="name" label="分类名称" rules={[{required:true,whitespace:true,message:'请输入分类名称'}]}><Input maxLength={100} /></Form.Item></Form></Modal>
        <Modal title={detail?.name} open={!!detail} onCancel={()=>setDetail(null)} footer={detail && <Button type="primary" href={detail.repo} target="_blank" rel="noopener noreferrer">访问 GitHub ↗</Button>}>{detail && <><p>{detail.description || '暂无简介'}</p>{detail.screenshot && <img className="detail-image" src={detail.screenshot} />}<p>分类：{detail.category || '待分类'}　平台：{detail.platforms.join('、')}</p><p>许可证：{detail.license || '未知'}　☆ {detail.stars ?? '—'}</p></>}</Modal>
    </ConfigProvider>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><AntApp><Main /></AntApp></React.StrictMode>);
