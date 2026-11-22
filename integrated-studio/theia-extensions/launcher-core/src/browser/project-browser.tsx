import * as React from '@theia/core/shared/react';
import { InstanceManager } from './instance-manager.js';

export type Platform = 'modrinth' | 'curseforge';
export type ProjectKind = 'modpack' | 'mod';

export interface ProjectHit {
    id: string;
    slug?: string;
    title: string;
    author?: string;
    description?: string;
    downloads: number;
    icon?: string | null;
    versions?: string[];
    url?: string;
}

export interface ProjectVersion {
    id: string;
    name: string;
    number?: string;
    gameVersions: string[];
    loaders: string[];
    date: string;
    type?: string;
}

const fmtDownloads = (n: number) => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(n);

/** Modrinth·CurseForge 프로젝트 검색 목록 */
export function ProjectBrowser(props: {
    manager: InstanceManager;
    platform: Platform;
    kind: ProjectKind;
    gameVersion?: string;
    loader?: string;
    picked?: ProjectHit;
    onPick: (hit: ProjectHit | undefined) => void;
}): React.ReactElement {
    const { manager, platform, kind, gameVersion, loader, picked, onPick } = props;
    const [query, setQuery] = React.useState('');
    const [hits, setHits] = React.useState<ProjectHit[]>([]);
    const [total, setTotal] = React.useState(0);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState('');
    const seq = React.useRef(0);

    const load = React.useCallback(async (q: string, offset: number) => {
        const my = ++seq.current;
        setLoading(true);
        setError('');
        try {
            const method = platform === 'modrinth' ? 'modrinth_search' : 'cf_search';
            const res = await manager.call<{ total: number; hits: ProjectHit[] }>(method,
                { query: q, kind, game_version: gameVersion ?? null, loader: loader ?? null, offset });
            if (my !== seq.current) { return; }
            setTotal(res.total);
            setHits(prev => offset === 0 ? res.hits : [...prev, ...res.hits]);
        } catch (e) {
            if (my === seq.current) { setError(e instanceof Error ? e.message : String(e)); }
        } finally {
            if (my === seq.current) { setLoading(false); }
        }
    }, [manager, platform, kind, gameVersion, loader]);

    // 검색어 입력 0.4초 뒤 검색
    React.useEffect(() => {
        const t = setTimeout(() => load(query, 0), query ? 400 : 0);
        return () => clearTimeout(t);
    }, [query, load]);

    return <div className='pb'>
        <div className='ni-table-tools'>
            <span className='codicon codicon-search' aria-hidden='true' />
            <input className='theia-input' value={query} spellCheck={false}
                placeholder={`${platform === 'modrinth' ? 'Modrinth' : 'CurseForge'}에서 ${kind === 'modpack' ? '모드팩' : '모드'} 검색`}
                aria-label='검색' onChange={e => setQuery(e.target.value)} />
            <span className='ni-count'>{loading ? '검색 중…' : `${total.toLocaleString()}개`}</span>
        </div>
        <div className='pb-list' role='listbox' aria-label='검색 결과'>
            {error && <div className='ni-empty ni-error'>{error}</div>}
            {!error && !loading && hits.length === 0 && <div className='ni-empty'>결과가 없습니다.</div>}
            {hits.map(h => <div key={h.id} role='option' aria-selected={picked?.id === h.id} tabIndex={-1}
                className={'pb-item' + (picked?.id === h.id ? ' selected' : '')} onClick={() => onPick(h)}>
                {h.icon ? <img className='pb-icon' src={h.icon} alt='' loading='lazy' /> : <div className='pb-icon pb-icon-empty' aria-hidden='true' />}
                <div className='pb-text'>
                    <div className='pb-title'><b>{h.title}</b>{h.author && <span className='ni-muted'> · {h.author}</span>}</div>
                    <div className='pb-desc'>{h.description}</div>
                </div>
                <div className='pb-meta'>
                    <span className='codicon codicon-cloud-download' aria-hidden='true' /> {fmtDownloads(h.downloads)}
                </div>
            </div>)}
            {hits.length > 0 && hits.length < total && <button className='theia-button secondary pb-more' disabled={loading}
                onClick={() => load(query, hits.length)}>더 보기</button>}
        </div>
    </div>;
}

/** 고른 프로젝트의 버전(파일) 목록 */
export function VersionList(props: {
    manager: InstanceManager;
    platform: Platform;
    projectId: string;
    gameVersion?: string;
    loader?: string;
    value?: string;
    onPick: (v: ProjectVersion | undefined) => void;
}): React.ReactElement {
    const { manager, platform, projectId, gameVersion, loader, value, onPick } = props;
    const [versions, setVersions] = React.useState<ProjectVersion[] | undefined>(undefined);
    const [error, setError] = React.useState('');

    React.useEffect(() => {
        let alive = true;
        setVersions(undefined);
        setError('');
        const method = platform === 'modrinth' ? 'modrinth_versions' : 'cf_files';
        const params = platform === 'modrinth'
            ? { project: projectId, game_version: gameVersion ?? null, loader: loader ?? null }
            : { mod_id: projectId, game_version: gameVersion ?? null, loader: loader ?? null };
        manager.call<ProjectVersion[]>(method, params).then(vs => {
            if (!alive) { return; }
            setVersions(vs);
            onPick(vs[0]);
        }).catch(e => alive && setError(e instanceof Error ? e.message : String(e)));
        return () => { alive = false; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [manager, platform, projectId, gameVersion, loader]);

    if (error) {
        return <div className='ni-empty ni-error'>{error}</div>;
    }
    if (!versions) {
        return <div className='ni-empty'>버전 목록 불러오는 중…</div>;
    }
    if (!versions.length) {
        return <div className='ni-empty ni-warn'>조건에 맞는 버전이 없습니다{gameVersion ? ` (Java ${gameVersion}${loader ? ` · ${loader}` : ''})` : ''}.</div>;
    }
    return <div className='ni-table' role='listbox' aria-label='버전 목록'>
        <div className='ni-row ni-head pb-vrow' aria-hidden='true'><span>버전</span><span>게임 버전</span><span>로더</span><span>날짜</span></div>
        {versions.map(v => <div key={v.id} role='option' aria-selected={v.id === value} tabIndex={-1}
            className={'ni-row pb-vrow' + (v.id === value ? ' selected' : '')} onClick={() => onPick(v)}>
            <span className='pb-vname' title={v.name}>{v.name}{v.type && v.type !== 'release' && <span className='ni-type t-snapshot'>{v.type === 'beta' ? '베타' : '알파'}</span>}</span>
            <span className='ni-muted pb-ellipsis' title={v.gameVersions.join(', ')}>{v.gameVersions.slice(0, 3).join(', ')}{v.gameVersions.length > 3 ? ' …' : ''}</span>
            <span className='ni-muted'>{v.loaders.join(', ')}</span>
            <span className='ni-muted'>{v.date}</span>
        </div>)}
    </div>;
}

/** CurseForge API 키 입력 (OS 자격 증명 저장소에 저장) */
export function CurseForgeKeyForm(props: {
    manager: InstanceManager;
    openUrl: (url: string) => void;
    onSaved: () => void;
}): React.ReactElement {
    const [key, setKey] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    const [error, setError] = React.useState('');
    const save = async () => {
        setBusy(true);
        setError('');
        try {
            await props.manager.call('cf_set_key', { key });
            props.onSaved();
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        } finally {
            setBusy(false);
        }
    };
    return <div className='pb-keyform'>
        <h3>CurseForge API 키가 필요합니다</h3>
        <p className='ni-muted'>CurseForge는 API 키가 있어야 검색하고 받을 수 있습니다. 개인용 키는 CurseForge 개발자 콘솔에서 무료로 만들 수 있습니다.</p>
        <ol className='ni-muted'>
            <li><a href='#' onClick={e => { e.preventDefault(); props.openUrl('https://console.curseforge.com/'); }}>console.curseforge.com</a>에 로그인</li>
            <li>API Keys 메뉴에서 키를 복사</li>
            <li>아래에 붙여 넣고 저장</li>
        </ol>
        <div className='pb-keyrow'>
            <input className='theia-input' type='password' value={key} placeholder='API 키' aria-label='CurseForge API 키'
                autoComplete='off' spellCheck={false} onChange={e => setKey(e.target.value)} />
            <button className='theia-button' disabled={!key.trim() || busy} onClick={save}>{busy ? '확인 중…' : '저장'}</button>
        </div>
        {error && <div className='ni-error'>{error}</div>}
        <p className='ni-hint'>키는 Windows 자격 증명 관리자에 저장되며 파일이나 설정에 평문으로 남지 않습니다.</p>
    </div>;
}
