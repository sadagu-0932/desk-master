import * as React from '@theia/core/shared/react';
import { ReactDialog } from '@theia/core/lib/browser/dialogs/react-dialog';
import { DialogError } from '@theia/core/lib/browser/dialogs';
import { CreateInstanceOptions, GameVersion, Loader, LOADER_LABELS, LoaderVersions } from '../common/index.js';
import { InstanceManager } from './instance-manager.js';
import { CurseForgeKeyForm, Platform, ProjectBrowser, ProjectHit, ProjectVersion, VersionList } from './project-browser.js';
import { errorMessage } from './report-errors.js';

/** 공통: 위쪽에서 고른 이름·그룹·아이콘 */
export interface InstanceLook {
    name?: string;
    group?: string;
    icon?: string;
}

export type CreateInstanceResult =
    | { kind: 'custom'; options: CreateInstanceOptions; installNow: boolean }
    | { kind: 'file'; path: string; look: InstanceLook; version?: string }
    | { kind: 'modrinth'; versionId: string; look: InstanceLook }
    | { kind: 'curseforge'; modId: string; fileId: string; look: InstanceLook };

/** 창이 바깥(파일 고르기, 링크 열기)에 부탁하는 일 */
export interface CreateInstanceServices {
    pickFile(): Promise<string | undefined>;
    pickFolder(): Promise<string | undefined>;
    openUrl(url: string): void;
}

interface ImportInfo {
    kind: 'mrpack' | 'curseforge' | 'prism' | 'prism-zip' | 'folder';
    launcherName?: string;
    needsVersion?: boolean;
    note?: string;
    name: string;
    version?: string;
    loader: string;
    loaderVersion?: string;
    files: number;
    supported: boolean;
    packVersion?: string;
    needsKey?: boolean;
}

type Source = 'custom' | 'file' | 'modrinth' | 'curseforge';
type VersionType = GameVersion['type'];

const TYPE_LABEL: Record<VersionType, string> = { release: '정식', snapshot: '스냅샷', old_beta: '베타', old_alpha: '알파' };
const ICON_COLORS = ['#4f7a2a', '#c95a1c', '#3a6a8a', '#6a5a8a', '#8a6a2a', '#2a7a6a', '#8a3a4a', '#5a5f57'];
const KIND_LABEL: Record<ImportInfo['kind'], string> = { mrpack: 'Modrinth 모드팩 (.mrpack)', curseforge: 'CurseForge 모드팩 (.zip)', prism: 'Prism Launcher·MultiMC 인스턴스(연결)', 'prism-zip': 'Prism Launcher·MultiMC 내보내기 (.zip)', folder: '인스턴스 폴더(연결)' };

const LOADERS: { id: Loader; label: string; available: boolean }[] = [
    { id: 'vanilla', label: '없음 (바닐라)', available: true },
    { id: 'fabric', label: 'Fabric', available: true },
    { id: 'neoforge', label: 'NeoForge', available: true },
    { id: 'forge', label: 'Forge', available: true },
    { id: 'quilt', label: 'Quilt', available: true },
];
const lkey = (loader: string, version: string): string => `${loader}:${version}`;

/**
 * 새 인스턴스 창 (Prism Launcher의 "인스턴스 추가" 배치를 참고).
 * 위: 아이콘·이름·그룹 / 왼쪽: 만드는 방법 / 오른쪽: 방법별 화면
 */
export class CreateInstanceDialog extends ReactDialog<CreateInstanceResult | undefined> {
    protected source: Source = 'custom';
    protected name = '';
    protected nameEdited = false;
    protected group = '';
    protected icon = ICON_COLORS[0];

    // 직접 만들기
    protected query = '';
    protected filters: Record<VersionType, boolean> = { release: true, snapshot: false, old_beta: false, old_alpha: false };
    protected versions: GameVersion[] = [];
    protected versionsLoading = true;
    protected versionsError = '';
    protected selected: string | undefined;
    protected loader: Loader = 'fabric';
    protected loaderInfo = new Map<string, LoaderVersions | 'loading' | Error>();
    /** 버전을 모르는 폴더를 연결할 때 사용자가 적는 게임 버전 */
    protected importVersion = '';
    /** 모드팩 찾아보기 로더 필터 */
    protected packLoader = 'all';
    protected loaderVersion: string | undefined;
    protected ccEnabled = true;
    protected installNow = true;
    protected installRow: HTMLLabelElement;

    // 파일 가져오기
    protected importPath: string | undefined;
    protected importInfo: ImportInfo | undefined;
    protected importError = '';
    protected importBusy = false;

    // Modrinth / CurseForge
    protected picked: Record<Platform, ProjectHit | undefined> = { modrinth: undefined, curseforge: undefined };
    protected pickedVersion: Record<Platform, ProjectVersion | undefined> = { modrinth: undefined, curseforge: undefined };
    protected cfHasKey: boolean | undefined;

    constructor(protected readonly manager: InstanceManager, protected readonly existingGroups: string[],
        protected readonly services: CreateInstanceServices) {
        super({ title: '새 인스턴스', maxWidth: 1100 });
        this.addClass('studio-newinst-dialog');
        this.appendCloseButton('취소');
        this.appendAcceptButton('만들기');

        this.installRow = document.createElement('label');
        this.installRow.className = 'studio-newinst-installnow';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = this.installNow;
        cb.addEventListener('change', () => { this.installNow = cb.checked; });
        this.installRow.append(cb, document.createTextNode('만든 뒤 바로 설치(게임 파일 받기)'));
        this.controlPanel.prepend(this.installRow);

        this.loadVersions();
        this.manager.call<{ hasKey: boolean }>('cf_key_status').then(s => { this.cfHasKey = s.hasKey; this.update(); })
            .catch(() => { this.cfHasKey = false; this.update(); });
    }

    protected get look(): InstanceLook {
        return { name: this.name.trim() || undefined, group: this.group.trim() || undefined, icon: this.icon };
    }

    get value(): CreateInstanceResult | undefined {
        switch (this.source) {
            case 'custom':
                return this.selected ? {
                    kind: 'custom', installNow: this.installNow, options: {
                        name: this.name.trim(), version: this.selected, loader: this.loader,
                        loaderVersion: this.loader !== 'vanilla' ? this.loaderVersion : undefined,
                        group: this.group.trim() || undefined, icon: this.icon,
                        ccEnabled: this.loader === 'fabric' ? this.ccEnabled : false,
                    },
                } : undefined;
            case 'file':
                return this.importPath && this.importInfo
                    ? { kind: 'file', path: this.importPath, look: this.look, version: this.importVersion.trim() || undefined } : undefined;
            case 'modrinth': {
                const v = this.pickedVersion.modrinth;
                return v ? { kind: 'modrinth', versionId: v.id, look: this.look } : undefined;
            }
            case 'curseforge': {
                const p = this.picked.curseforge;
                const v = this.pickedVersion.curseforge;
                return p && v ? { kind: 'curseforge', modId: p.id, fileId: v.id, look: this.look } : undefined;
            }
        }
    }

    protected isValid(value: CreateInstanceResult | undefined): DialogError {
        if (this.source === 'file') {
            if (this.importBusy) { return '파일을 확인하는 중입니다.'; }
            if (!value) { return '가져올 파일이나 폴더를 고르세요.'; }
            if (this.importInfo?.needsVersion && !/^\d+\.\d+(\.\d+)?$/.test(this.importVersion.trim())) {
                return '이 폴더의 게임 버전을 찾지 못했습니다. 게임 버전을 적어 주세요(예: 26.3).';
            }
            if (this.importInfo && !this.importInfo.supported) {
                return `${this.importInfo.loader} 로더용이라 가져올 수 없습니다(바닐라·Fabric·Quilt·NeoForge·Forge 지원).`;
            }
            if (this.importInfo?.needsKey) { return 'CurseForge 모드팩은 API 키가 필요합니다. 왼쪽 CurseForge 탭에서 키를 저장하세요.'; }
            return '';
        }
        if (this.source === 'modrinth' || this.source === 'curseforge') {
            if (this.source === 'curseforge' && !this.cfHasKey) { return 'CurseForge API 키를 먼저 저장하세요.'; }
            if (!this.picked[this.source]) { return '모드팩을 고르세요.'; }
            if (!value) { return '버전을 고르세요.'; }
            const v = this.pickedVersion[this.source];
            if (v && v.loaders.length && !v.loaders.some(l => l in LOADER_LABELS || l === 'minecraft')) {
                return `이 버전은 ${v.loaders.join(', ')}용입니다(바닐라·Fabric·Quilt·NeoForge·Forge 지원).`;
            }
            return '';
        }
        if (!value || value.kind !== 'custom') { return '버전을 고르세요.'; }
        if (!value.options.name) { return '이름을 입력하세요.'; }
        if (value.options.loader !== 'vanilla') {
            const name = LOADER_LABELS[value.options.loader] ?? value.options.loader;
            const info = this.loaderInfo.get(lkey(value.options.loader, value.options.version));
            if (info === 'loading' || info === undefined) { return `${name} 로더 목록을 불러오는 중입니다.`; }
            if (info instanceof Error) { return `${name} 로더 목록을 받지 못했습니다: ${info.message}`; }
            if (!info.supported) { return `${name}이(가) ${value.options.version}을(를) 아직 지원하지 않습니다. 로더를 바꾸세요.`; }
        }
        return '';
    }

    protected refresh(): void {
        this.update();
        this.validate();
    }

    protected setSource(s: Source): void {
        this.source = s;
        this.installRow.style.visibility = s === 'custom' ? 'visible' : 'hidden';
        this.acceptButton!.textContent = s === 'custom' ? '만들기' : '가져오기';
        this.autoName();
        this.refresh();
    }

    /** 이름을 직접 고치지 않았으면 고른 것에 맞춰 채운다 */
    protected autoName(): void {
        if (this.nameEdited) { return; }
        const n = this.source === 'custom' ? this.selected
            : this.source === 'file' ? this.importInfo?.name
                : this.picked[this.source]?.title;
        this.name = n ?? '';
    }

    // ---------- 직접 만들기: 데이터 ----------
    protected async loadVersions(): Promise<void> {
        this.versionsLoading = true;
        this.versionsError = '';
        this.update();
        try {
            this.versions = await this.manager.listVersions(true);
            if (!this.selected) { this.select(this.versions.find(v => v.type === 'release')?.id); }
        } catch (e) {
            this.versionsError = errorMessage(e);
        } finally {
            this.versionsLoading = false;
            this.refresh();
        }
    }

    protected select(id: string | undefined): void {
        this.selected = id;
        this.autoName();
        this.loaderVersion = undefined;
        this.refresh();
        if (id && this.loader !== 'vanilla') { this.loadLoaderVersions(id); }
    }

    protected async loadLoaderVersions(version: string): Promise<void> {
        const key = lkey(this.loader, version);
        const cached = this.loaderInfo.get(key);
        if (cached && !(cached instanceof Error)) { this.pickDefaultLoader(version); return; }
        this.loaderInfo.set(key, 'loading');
        this.update();
        try {
            this.loaderInfo.set(key, await this.manager.listLoaderVersions(version, this.loader));
        } catch (e) {
            this.loaderInfo.set(key, e instanceof Error ? e : new Error(String(e)));
        }
        this.pickDefaultLoader(version);
    }

    protected pickDefaultLoader(version: string): void {
        const info = this.loaderInfo.get(lkey(this.loader, version));
        if (this.selected === version && info && info !== 'loading' && !(info instanceof Error) && !this.loaderVersion) {
            this.loaderVersion = (info.versions.find(v => v.stable) ?? info.versions[0])?.version;
        }
        this.refresh();
    }

    protected setLoader(id: Loader): void {
        this.loader = id;
        this.loaderVersion = undefined;
        this.refresh();
        if (id !== 'vanilla' && this.selected) { this.loadLoaderVersions(this.selected); }
    }

    // ---------- 파일 가져오기 ----------
    protected async choose(folder: boolean): Promise<void> {
        const p = folder ? await this.services.pickFolder() : await this.services.pickFile();
        if (!p) { return; }
        this.importPath = p;
        this.importInfo = undefined;
        this.importVersion = '';
        this.importError = '';
        this.importBusy = true;
        this.refresh();
        try {
            this.importInfo = await this.manager.call<ImportInfo>('inspect_import', { path: p });
            this.autoName();
        } catch (e) {
            this.importError = errorMessage(e);
            this.importPath = undefined;
        } finally {
            this.importBusy = false;
            this.refresh();
        }
    }

    // ---------- 화면 ----------
    protected render(): React.ReactNode {
        const src = (id: Source, icon: string, label: string) =>
            <button className={'ni-source' + (this.source === id ? ' active' : '')} aria-current={this.source === id ? 'page' : undefined}
                onClick={() => this.setSource(id)}>
                <span className={`codicon codicon-${icon}`} aria-hidden='true' />{label}
            </button>;
        return <div className='studio-newinst'>
            {this.renderTop()}
            <div className='ni-body'>
                <nav className='ni-sources' aria-label='만드는 방법'>
                    {src('custom', 'add', '직접 만들기')}
                    {src('file', 'archive', '파일 가져오기')}
                    <div className='ni-source-sep'>온라인</div>
                    {src('modrinth', 'package', 'Modrinth')}
                    {src('curseforge', 'flame', 'CurseForge')}
                    <div className='ni-source-sep'>미지원</div>
                    {['ATLauncher', 'FTB', 'Technic'].map(n => <button key={n} className='ni-source' disabled title='지원하지 않습니다'>
                        <span className='codicon codicon-circle-slash' aria-hidden='true' />{n}
                    </button>)}
                </nav>
                <div className='ni-main'>
                    {this.source === 'custom' && <>{this.renderVersions()}{this.renderLoader()}</>}
                    {this.source === 'file' && this.renderFile()}
                    {(this.source === 'modrinth' || this.source === 'curseforge') && this.renderPlatform(this.source)}
                </div>
            </div>
        </div>;
    }

    protected renderTop(): React.ReactNode {
        return <div className='ni-top'>
            <div className='ni-icon-picker' role='radiogroup' aria-label='아이콘 색'>
                <div className='ni-icon-preview' style={{ background: this.icon }} aria-hidden='true' />
                <div className='ni-icon-swatches'>
                    {ICON_COLORS.map(c => <button key={c} role='radio' aria-checked={c === this.icon} aria-label={`아이콘 색 ${c}`}
                        className={'ni-swatch' + (c === this.icon ? ' on' : '')} style={{ background: c }}
                        onClick={() => { this.icon = c; this.update(); }} />)}
                </div>
            </div>
            <div className='ni-fields'>
                <label className='ni-field'>
                    <span>이름</span>
                    <input className='theia-input' value={this.name} placeholder={this.source === 'custom' ? '예: 캠핑장 맵' : '(비우면 모드팩 이름)'} autoFocus spellCheck={false}
                        onChange={e => { this.name = e.target.value; this.nameEdited = !!e.target.value; this.refresh(); }} />
                </label>
                <label className='ni-field'>
                    <span>그룹</span>
                    <input className='theia-input' value={this.group} placeholder='(선택) 예: 맵 제작' list='studio-newinst-groups' spellCheck={false}
                        onChange={e => { this.group = e.target.value; this.update(); }} />
                    <datalist id='studio-newinst-groups'>{this.existingGroups.map(g => <option key={g} value={g} />)}</datalist>
                </label>
            </div>
        </div>;
    }

    protected renderVersions(): React.ReactNode {
        const q = this.query.trim().toLowerCase();
        const list = this.versions.filter(v => this.filters[v.type] && (!q || v.id.toLowerCase().includes(q)));
        return <section className='ni-versions' aria-label='게임 버전'>
            <div className='ni-table-wrap'>
                <div className='ni-table-tools'>
                    <span className='codicon codicon-search' aria-hidden='true' />
                    <input className='theia-input' value={this.query} placeholder='버전 검색 (예: 26.3)' aria-label='버전 검색' spellCheck={false}
                        onChange={e => { this.query = e.target.value; this.update(); }} />
                    <span className='ni-count'>{this.versionsLoading ? '불러오는 중…' : `${list.length}개`}</span>
                </div>
                <div className='ni-table' role='listbox' aria-label='버전 목록'>
                    <div className='ni-row ni-head' aria-hidden='true'><span>버전</span><span>출시일</span><span>종류</span></div>
                    {this.versionsError && <div className='ni-empty ni-error'>버전 목록을 받지 못했습니다: {this.versionsError}</div>}
                    {!this.versionsError && !this.versionsLoading && list.length === 0 && <div className='ni-empty'>조건에 맞는 버전이 없습니다.</div>}
                    {list.map(v => <div key={v.id} role='option' aria-selected={v.id === this.selected} tabIndex={-1}
                        className={'ni-row' + (v.id === this.selected ? ' selected' : '')} onClick={() => this.select(v.id)}>
                        <span className='ni-mono'>{v.id}</span>
                        <span className='ni-muted'>{v.released}</span>
                        <span className={'ni-type t-' + v.type}>{TYPE_LABEL[v.type]}</span>
                    </div>)}
                </div>
            </div>
            <aside className='ni-filters' aria-label='버전 종류 필터'>
                <div className='ni-subtitle'>보이기</div>
                {(Object.keys(TYPE_LABEL) as VersionType[]).map(t => <label key={t} className='ni-check'>
                    <input type='checkbox' checked={this.filters[t]} onChange={e => { this.filters[t] = e.target.checked; this.update(); }} />{TYPE_LABEL[t]}
                </label>)}
                <button className='theia-button secondary ni-refresh' onClick={() => this.loadVersions()}>
                    <span className='codicon codicon-refresh' aria-hidden='true' /> 새로고침
                </button>
            </aside>
        </section>;
    }

    protected renderLoader(): React.ReactNode {
        const info = this.selected ? this.loaderInfo.get(lkey(this.loader, this.selected)) : undefined;
        return <section className='ni-loader' aria-label='모드 로더'>
            <div className='ni-loader-kinds' role='radiogroup' aria-label='모드 로더'>
                <div className='ni-subtitle'>모드 로더</div>
                {LOADERS.map(l => <label key={l.id} className={'ni-check' + (l.available ? '' : ' disabled')}>
                    <input type='radio' name='studio-loader' disabled={!l.available} checked={this.loader === l.id}
                        onChange={() => l.available && this.setLoader(l.id as Loader)} />
                    {l.label}{!l.available && <span className='ni-soon'>미지원</span>}
                </label>)}
            </div>
            <div className='ni-loader-versions'>
                {this.loader === 'vanilla'
                    ? <div className='ni-empty'>모드 없이 바닐라로 만듭니다. 데이터팩과 리소스팩은 쓸 수 있습니다.</div>
                    : this.renderLoaderVersions(info)}
            </div>
            <aside className='ni-loader-options'>
                <div className='ni-subtitle'>함께 설치</div>
                <label className={'ni-check' + (this.loader === 'fabric' ? '' : ' disabled')}>
                    <input type='checkbox' disabled={this.loader !== 'fabric'} checked={this.loader === 'fabric' && this.ccEnabled}
                        onChange={e => { this.ccEnabled = e.target.checked; this.update(); }} />
                    CommandCrafter 모드
                </label>
                <p className='ni-hint'>데이터팩 자동완성·디버거·/reload 버튼에 필요합니다. 나중에 켜고 끌 수 있습니다.</p>
            </aside>
        </section>;
    }

    protected renderLoaderVersions(info: LoaderVersions | 'loading' | Error | undefined): React.ReactNode {
        if (!this.selected) { return <div className='ni-empty'>먼저 게임 버전을 고르세요.</div>; }
        const name = LOADER_LABELS[this.loader] ?? this.loader;
        if (info === undefined || info === 'loading') { return <div className='ni-empty'>{name} 로더 목록 불러오는 중…</div>; }
        if (info instanceof Error) {
            return <div className='ni-empty ni-error'>{name} 로더 목록을 받지 못했습니다: {info.message}
                <button className='theia-button secondary' onClick={() => { this.loaderInfo.delete(lkey(this.loader, this.selected!)); this.loadLoaderVersions(this.selected!); }}>다시 시도</button>
            </div>;
        }
        if (!info.supported) { return <div className='ni-empty ni-warn'>{name}이(가) {this.selected}을(를) 아직 지원하지 않습니다.</div>; }
        return <div className='ni-table ni-table-small' role='listbox' aria-label={`${name} 로더 버전`}>
            <div className='ni-row ni-head ni-row-2' aria-hidden='true'><span>{name} 로더 버전</span><span /></div>
            {info.versions.map((v, i) => <div key={v.version} role='option' aria-selected={v.version === this.loaderVersion} tabIndex={-1}
                className={'ni-row ni-row-2' + (v.version === this.loaderVersion ? ' selected' : '')}
                onClick={() => { this.loaderVersion = v.version; this.update(); }}>
                <span className='ni-mono'>{v.version}</span>
                <span>{v.stable && i === info.versions.findIndex(x => x.stable) ? <span className='ni-type t-release'>추천</span>
                    : /beta|alpha|rc|pre/i.test(v.version) ? <span className='ni-muted'>베타</span> : ''}</span>
            </div>)}
        </div>;
    }

    protected renderFile(): React.ReactNode {
        const info = this.importInfo;
        return <section className='ni-file'>
            <div className='ni-file-pick'>
                <button className='theia-button' onClick={() => this.choose(false)}>
                    <span className='codicon codicon-file-zip' aria-hidden='true' /> 모드팩 파일 고르기 (.mrpack / .zip)
                </button>
                <button className='theia-button secondary' onClick={() => this.choose(true)}>
                    <span className='codicon codicon-folder' aria-hidden='true' /> 인스턴스 폴더 연결 (어느 런처든)
                </button>
            </div>
            <ul className='ni-file-kinds ni-muted'>
                <li><b>.mrpack</b> — Modrinth 모드팩 파일</li>
                <li><b>.zip</b> — CurseForge 모드팩 파일 (안의 모드를 받으려면 CurseForge API 키 필요)</li>
                <li><b>폴더</b> — Prism·MultiMC·CurseForge·Modrinth App 인스턴스 폴더, 또는 mods·saves 가 든 게임 폴더(.minecraft).
                    폴더는 원래 자리에 그대로 두고 바로 연결합니다 — 아무것도 받지 않습니다. Prism·MultiMC 는 실행하면 그 런처가 켭니다.</li>
            </ul>
            {this.importBusy && <div className='ni-empty'>확인하는 중…</div>}
            {this.importError && <div className='ni-empty ni-error'>{this.importError}</div>}
            {info && this.importPath && <div className={'ni-file-card' + (info.supported ? '' : ' bad')}>
                <div className='ni-subtitle'>{info.kind === 'folder' ? `${info.launcherName ?? '폴더'} 인스턴스 (연결 — 받는 것 없음)` : KIND_LABEL[info.kind]}</div>
                <h3>{info.name}{info.packVersion ? <span className='ni-muted'> {info.packVersion}</span> : ''}</h3>
                <div className='studio-tags'>
                    <span className='ni-type'>Java {info.version ?? '?'}</span>
                    <span className={'ni-type' + (info.supported ? ' t-release' : ' t-snapshot')}>{info.loader}{info.loaderVersion ? ` ${info.loaderVersion}` : ''}</span>
                    <span className='ni-type'>{info.kind === 'prism' || info.kind === 'folder' ? `모드 ${info.files}개` : `받을 파일 ${info.files}개`}</span>
                </div>
                <div className='ni-mono ni-muted ni-path' title={this.importPath}>{this.importPath}</div>
                {info.needsVersion && <label className='ni-field'>게임 버전(로그에서 못 찾음)
                    <input className='theia-input' placeholder='예: 26.3' value={this.importVersion}
                        onChange={e => { this.importVersion = e.target.value; this.refresh(); }} />
                </label>}
            </div>}
        </section>;
    }

    protected renderPlatform(platform: Platform): React.ReactNode {
        if (platform === 'curseforge' && this.cfHasKey === false) {
            return <CurseForgeKeyForm manager={this.manager} openUrl={u => this.services.openUrl(u)}
                onSaved={() => { this.cfHasKey = true; this.refresh(); }} />;
        }
        if (platform === 'curseforge' && this.cfHasKey === undefined) {
            return <div className='ni-empty'>확인하는 중…</div>;
        }
        const picked = this.picked[platform];
        const lf = this.packLoader === 'all' ? undefined : this.packLoader;
        return <section className='ni-platform'>
            <label className='ni-pack-loader'>로더
                <select className='theia-select' value={this.packLoader} aria-label='모드팩 로더'
                    onChange={e => { this.packLoader = e.target.value; this.picked[platform] = undefined; this.pickedVersion[platform] = undefined; this.refresh(); }}>
                    <option value='all'>전체</option>
                    {(['fabric', 'neoforge', 'forge', 'quilt'] as const).map(l => <option key={l} value={l}>{LOADER_LABELS[l]}</option>)}
                </select>
            </label>
            <ProjectBrowser key={`${platform}:${this.packLoader}`} manager={this.manager} platform={platform} kind='modpack' loader={lf} picked={picked}
                onPick={h => {
                    if (h?.id === picked?.id) { return; }
                    this.picked[platform] = h; this.pickedVersion[platform] = undefined; this.autoName(); this.refresh();
                }} />
            <div className='ni-platform-versions'>
                <div className='ni-subtitle'>{picked ? `${picked.title} 버전` : '모드팩 버전'}
                    {picked?.url && <a href='#' className='ni-link' onClick={e => { e.preventDefault(); this.services.openUrl(picked.url!); }}>페이지 열기</a>}
                </div>
                {picked
                    ? <VersionList manager={this.manager} platform={platform} projectId={picked.id} loader={lf}
                        value={this.pickedVersion[platform]?.id}
                        onPick={v => { this.pickedVersion[platform] = v; this.refresh(); }} />
                    : <div className='ni-empty'>위에서 모드팩을 고르세요. 위 [로더]로 Fabric·NeoForge·Forge·Quilt 만 볼 수 있습니다.</div>}
            </div>
        </section>;
    }
}
