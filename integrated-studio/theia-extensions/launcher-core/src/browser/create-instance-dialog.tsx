import * as React from '@theia/core/shared/react';
import { ReactDialog } from '@theia/core/lib/browser/dialogs/react-dialog';
import { DialogError } from '@theia/core/lib/browser/dialogs';
import { CreateInstanceOptions, GameVersion, Loader, LoaderVersions } from '../common/index.js';
import { InstanceManager } from './instance-manager.js';

export interface CreateInstanceResult {
    options: CreateInstanceOptions;
    installNow: boolean;
}

type VersionType = GameVersion['type'];

const TYPE_LABEL: Record<VersionType, string> = {
    release: '정식',
    snapshot: '스냅샷',
    old_beta: '베타',
    old_alpha: '알파',
};

const ICON_COLORS = ['#4f7a2a', '#c95a1c', '#3a6a8a', '#6a5a8a', '#8a6a2a', '#2a7a6a', '#8a3a4a', '#5a5f57'];

interface LoaderChoice {
    id: Loader | 'neoforge' | 'quilt';
    label: string;
    available: boolean;
}

const LOADERS: LoaderChoice[] = [
    { id: 'vanilla', label: '없음 (바닐라)', available: true },
    { id: 'fabric', label: 'Fabric', available: true },
    { id: 'neoforge', label: 'NeoForge', available: false },
    { id: 'quilt', label: 'Quilt', available: false },
];

/**
 * 새 인스턴스 만들기 창 (Prism Launcher의 "인스턴스 추가" 배치를 참고).
 * 위: 아이콘·이름·그룹 / 왼쪽: 만드는 방법 / 가운데: 버전 표 + 종류 필터 / 아래: 모드 로더와 로더 버전
 */
export class CreateInstanceDialog extends ReactDialog<CreateInstanceResult | undefined> {
    protected name = '';
    protected nameEdited = false;
    protected group = '';
    protected icon = ICON_COLORS[0];
    protected query = '';
    protected filters: Record<VersionType, boolean> = { release: true, snapshot: false, old_beta: false, old_alpha: false };
    protected versions: GameVersion[] = [];
    protected versionsLoading = true;
    protected versionsError = '';
    protected selected: string | undefined;
    protected loader: Loader = 'fabric';
    protected loaderInfo = new Map<string, LoaderVersions | 'loading' | Error>();
    protected loaderVersion: string | undefined;
    protected ccEnabled = true;
    protected installNow = true;
    protected installCheckbox: HTMLInputElement;

    constructor(protected readonly manager: InstanceManager, protected readonly existingGroups: string[]) {
        super({ title: '새 인스턴스', maxWidth: 1100 });
        this.addClass('studio-newinst-dialog');
        this.appendCloseButton('취소');
        this.appendAcceptButton('만들기');

        // 아래쪽 버튼 줄 왼쪽: 만든 뒤 바로 설치
        const label = document.createElement('label');
        label.className = 'studio-newinst-installnow';
        this.installCheckbox = document.createElement('input');
        this.installCheckbox.type = 'checkbox';
        this.installCheckbox.checked = this.installNow;
        this.installCheckbox.addEventListener('change', () => { this.installNow = this.installCheckbox.checked; });
        label.append(this.installCheckbox, document.createTextNode('만든 뒤 바로 설치(게임 파일 받기)'));
        this.controlPanel.prepend(label);

        this.loadVersions();
    }

    get value(): CreateInstanceResult | undefined {
        if (!this.selected) {
            return undefined;
        }
        return {
            installNow: this.installNow,
            options: {
                name: this.name.trim(),
                version: this.selected,
                loader: this.loader,
                loaderVersion: this.loader === 'fabric' ? this.loaderVersion : undefined,
                group: this.group.trim() || undefined,
                icon: this.icon,
                ccEnabled: this.loader === 'fabric' ? this.ccEnabled : false,
            },
        };
    }

    protected isValid(value: CreateInstanceResult | undefined): DialogError {
        if (!value) {
            return '버전을 고르세요.';
        }
        if (!value.options.name) {
            return '이름을 입력하세요.';
        }
        if (value.options.loader === 'fabric') {
            const info = this.loaderInfo.get(value.options.version);
            if (info === 'loading' || info === undefined) {
                return 'Fabric 로더 목록을 불러오는 중입니다.';
            }
            if (info instanceof Error) {
                return `Fabric 로더 목록을 받지 못했습니다: ${info.message}`;
            }
            if (!info.supported) {
                return `Fabric이 ${value.options.version}을(를) 아직 지원하지 않습니다. 로더를 "없음"으로 바꾸세요.`;
            }
        }
        return '';
    }

    // ---------- 데이터 ----------
    protected async loadVersions(): Promise<void> {
        this.versionsLoading = true;
        this.versionsError = '';
        this.update();
        try {
            this.versions = await this.manager.listVersions(true);
            if (!this.selected) {
                this.select(this.versions.find(v => v.type === 'release')?.id);
            }
        } catch (e) {
            this.versionsError = e instanceof Error ? e.message : String(e);
        } finally {
            this.versionsLoading = false;
            this.update();
            this.validate();
        }
    }

    protected select(id: string | undefined): void {
        this.selected = id;
        if (id && !this.nameEdited) {
            this.name = id;
        }
        this.loaderVersion = undefined;
        this.update();
        this.validate();
        if (id && this.loader === 'fabric') {
            this.loadLoaderVersions(id);
        }
    }

    protected async loadLoaderVersions(version: string): Promise<void> {
        const cached = this.loaderInfo.get(version);
        if (cached && !(cached instanceof Error)) {
            this.pickDefaultLoader(version);
            return;
        }
        this.loaderInfo.set(version, 'loading');
        this.update();
        try {
            this.loaderInfo.set(version, await this.manager.listLoaderVersions(version, 'fabric'));
        } catch (e) {
            this.loaderInfo.set(version, e instanceof Error ? e : new Error(String(e)));
        }
        this.pickDefaultLoader(version);
    }

    protected pickDefaultLoader(version: string): void {
        const info = this.loaderInfo.get(version);
        if (this.selected === version && info && info !== 'loading' && !(info instanceof Error) && !this.loaderVersion) {
            this.loaderVersion = (info.versions.find(v => v.stable) ?? info.versions[0])?.version;
        }
        this.update();
        this.validate();
    }

    protected setLoader(id: Loader): void {
        this.loader = id;
        this.update();
        this.validate();
        if (id === 'fabric' && this.selected) {
            this.loadLoaderVersions(this.selected);
        }
    }

    protected get filteredVersions(): GameVersion[] {
        const q = this.query.trim().toLowerCase();
        return this.versions.filter(v => this.filters[v.type] && (!q || v.id.toLowerCase().includes(q)));
    }

    // ---------- 화면 ----------
    protected render(): React.ReactNode {
        return <div className='studio-newinst'>
            {this.renderTop()}
            <div className='ni-body'>
                <nav className='ni-sources' aria-label='만드는 방법'>
                    <button className='ni-source active' aria-current='page'>
                        <span className='codicon codicon-add' aria-hidden='true' />직접 만들기
                    </button>
                    <button className='ni-source' disabled title='준비 중'>
                        <span className='codicon codicon-archive' aria-hidden='true' />가져오기 (.mrpack)<span className='ni-soon'>준비 중</span>
                    </button>
                    <button className='ni-source' disabled title='준비 중'>
                        <span className='codicon codicon-package' aria-hidden='true' />Modrinth 모드팩<span className='ni-soon'>준비 중</span>
                    </button>
                </nav>
                <div className='ni-main'>
                    {this.renderVersions()}
                    {this.renderLoader()}
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
                    <input className='theia-input' value={this.name} placeholder='예: 캠핑장 맵' autoFocus spellCheck={false}
                        onChange={e => { this.name = e.target.value; this.nameEdited = true; this.update(); this.validate(); }} />
                </label>
                <label className='ni-field'>
                    <span>그룹</span>
                    <input className='theia-input' value={this.group} placeholder='(선택) 예: 맵 제작' list='studio-newinst-groups' spellCheck={false}
                        onChange={e => { this.group = e.target.value; this.update(); }} />
                    <datalist id='studio-newinst-groups'>
                        {this.existingGroups.map(g => <option key={g} value={g} />)}
                    </datalist>
                </label>
            </div>
        </div>;
    }

    protected renderVersions(): React.ReactNode {
        const list = this.filteredVersions;
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
                        className={'ni-row' + (v.id === this.selected ? ' selected' : '')}
                        onClick={() => this.select(v.id)}>
                        <span className='ni-mono'>{v.id}</span>
                        <span className='ni-muted'>{v.released}</span>
                        <span className={'ni-type t-' + v.type}>{TYPE_LABEL[v.type]}</span>
                    </div>)}
                </div>
            </div>
            <aside className='ni-filters' aria-label='버전 종류 필터'>
                <div className='ni-subtitle'>보이기</div>
                {(Object.keys(TYPE_LABEL) as VersionType[]).map(t => <label key={t} className='ni-check'>
                    <input type='checkbox' checked={this.filters[t]}
                        onChange={e => { this.filters[t] = e.target.checked; this.update(); }} />{TYPE_LABEL[t]}
                </label>)}
                <button className='theia-button secondary ni-refresh' onClick={() => this.loadVersions()}>
                    <span className='codicon codicon-refresh' aria-hidden='true' /> 새로고침
                </button>
            </aside>
        </section>;
    }

    protected renderLoader(): React.ReactNode {
        const info = this.selected ? this.loaderInfo.get(this.selected) : undefined;
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
                    : this.renderFabricVersions(info)}
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

    protected renderFabricVersions(info: LoaderVersions | 'loading' | Error | undefined): React.ReactNode {
        if (!this.selected) {
            return <div className='ni-empty'>먼저 게임 버전을 고르세요.</div>;
        }
        if (info === undefined || info === 'loading') {
            return <div className='ni-empty'>Fabric 로더 목록 불러오는 중…</div>;
        }
        if (info instanceof Error) {
            return <div className='ni-empty ni-error'>Fabric 로더 목록을 받지 못했습니다: {info.message}
                <button className='theia-button secondary' onClick={() => { this.loaderInfo.delete(this.selected!); this.loadLoaderVersions(this.selected!); }}>다시 시도</button>
            </div>;
        }
        if (!info.supported) {
            return <div className='ni-empty ni-warn'>Fabric이 {this.selected}을(를) 아직 지원하지 않습니다.</div>;
        }
        return <div className='ni-table ni-table-small' role='listbox' aria-label='Fabric 로더 버전'>
            <div className='ni-row ni-head ni-row-2' aria-hidden='true'><span>Fabric 로더 버전</span><span /></div>
            {info.versions.map((v, i) => <div key={v.version} role='option' aria-selected={v.version === this.loaderVersion} tabIndex={-1}
                className={'ni-row ni-row-2' + (v.version === this.loaderVersion ? ' selected' : '')}
                onClick={() => { this.loaderVersion = v.version; this.update(); }}>
                <span className='ni-mono'>{v.version}</span>
                <span>{v.stable && i === info.versions.findIndex(x => x.stable) ? <span className='ni-type t-release'>추천</span>
                    : /beta|alpha|rc|pre/i.test(v.version) ? <span className='ni-muted'>베타</span> : ''}</span>
            </div>)}
        </div>;
    }
}
