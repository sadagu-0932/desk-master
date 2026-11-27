import * as React from '@theia/core/shared/react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser/widgets/react-widget';
import { codicon } from '@theia/core/lib/browser/widgets';
import { CommandService } from '@theia/core/lib/common/command';
import { MessageService } from '@theia/core/lib/common/message-service';
import { FileDialogService } from '@theia/filesystem/lib/browser/file-dialog/file-dialog-service';
import { FileUri } from '@theia/core/lib/common/file-uri';
import { InstanceManager } from 'integrated-studio-launcher-core/lib/browser';
import { LOADER_LABELS } from 'integrated-studio-launcher-core/lib/common';
import { DetectedInstance, ImportPreview, ImportResult, formatBytes } from '../common/index.js';
import { ServerHostStore } from './server-host-store.js';
import { ServerHostCommands } from './server-host-commands.js';

const LAUNCHER_ICON: Record<string, string> = {
    prism: 'layers', multimc: 'layers', curseforge: 'flame', modrinth: 'package', official: 'home', folder: 'folder',
};

type Step = 'list' | 'preview' | 'running' | 'done';

/** 다른 런처 인스턴스 불러오기: 감지 목록 → 미리보기(옮길 폴더·용량·방식) → 불러오기 → 완료([서버로 열기]). */
@injectable()
export class ImportWidget extends ReactWidget {
    static readonly ID = 'studio-import-instances';
    static readonly LABEL = '인스턴스 불러오기';

    @inject(ServerHostStore) protected readonly store: ServerHostStore;
    @inject(CommandService) protected readonly commands: CommandService;
    @inject(MessageService) protected readonly messages: MessageService;
    @inject(FileDialogService) protected readonly fileDialog: FileDialogService;
    @inject(InstanceManager) protected readonly instances: InstanceManager;

    protected step: Step = 'list';
    protected loading = false;
    protected entries: DetectedInstance[] = [];
    protected selected = new Set<string>();
    protected versions = new Map<string, string>();
    protected mode: 'copy' | 'link' = 'link';
    protected preview: ImportPreview | undefined;
    protected result: ImportResult | undefined;
    protected error: string | undefined;

    @postConstruct()
    protected init(): void {
        this.id = ImportWidget.ID;
        this.title.label = ImportWidget.LABEL;
        this.title.caption = '다른 런처(Prism·MultiMC·CurseForge·Modrinth App·공식 런처)의 인스턴스를 불러옵니다';
        this.title.iconClass = codicon('cloud-download');
        this.title.closable = true;
        this.addClass('studio-import');
        this.detect();
    }

    protected async detect(): Promise<void> {
        this.loading = true;
        this.error = undefined;
        this.update();
        try {
            this.entries = await this.store.service.importDetect();
        } catch (e) {
            this.error = (e as Error).message;
        }
        this.loading = false;
        this.update();
    }

    protected async pickFolder(): Promise<void> {
        const uri = await this.fileDialog.showOpenDialog({ title: '인스턴스 폴더 고르기', openLabel: '고르기', canSelectFiles: false, canSelectFolders: true });
        const one = Array.isArray(uri) ? uri[0] : uri;
        if (!one) {
            return;
        }
        const found = await this.store.service.importInspectFolder(FileUri.fsPath(one));
        if (!found.length) {
            this.messages.warn('이 폴더에서 인스턴스를 찾지 못했습니다(mmc-pack.json·minecraftinstance.json·launcher_profiles.json·app.db·mods/saves 없음).');
            return;
        }
        const keys = new Set(this.entries.map(e => e.key));
        this.entries = [...found.filter(e => !keys.has(e.key)), ...this.entries];
        found.forEach(e => this.selected.add(e.key));
        this.update();
    }

    protected toggle(e: DetectedInstance): void {
        if (this.selected.has(e.key)) {
            this.selected.delete(e.key);
        } else {
            this.selected.add(e.key);
        }
        this.update();
    }

    protected async showPreview(): Promise<void> {
        this.preview = await this.store.service.importPreview([...this.selected], this.mode);
        this.step = 'preview';
        this.update();
    }

    protected async run(): Promise<void> {
        this.step = 'running';
        this.update();
        try {
            this.result = await this.store.service.importRun(
                [...this.selected].map(key => ({ key, version: this.versions.get(key) || undefined })), this.mode);
            await this.instances.refresh();
            this.result.imported.forEach(i => this.instances.ensureVisible(i.id, i.name));
            this.step = 'done';
        } catch (e) {
            this.error = (e as Error).message;
            this.step = 'preview';
        }
        this.update();
    }

    protected render(): React.ReactNode {
        return <div className='imp-root'>
            <h2>다른 런처 인스턴스 불러오기</h2>
            {this.error && <div className='sh-note error'>{this.error}</div>}
            {this.step === 'list' && this.renderList()}
            {this.step === 'preview' && this.renderPreview()}
            {this.step === 'running' && <div className='imp-running'><span className={codicon('loading') + ' codicon-modifier-spin'} /> 불러오는 중… (진행은 아래 알림에 나옵니다)</div>}
            {this.step === 'done' && this.renderDone()}
        </div>;
    }

    protected renderList(): React.ReactNode {
        const need = [...this.selected].filter(k => !this.entries.find(e => e.key === k)?.version && !this.versions.get(k));
        return <>
            <div className='sh-actions'>
                <button className='theia-button secondary' onClick={() => this.detect()}><span className={codicon('refresh')} /> 다시 찾기</button>
                <button className='theia-button secondary' onClick={() => this.pickFolder()}><span className={codicon('folder-opened')} /> 폴더 직접 고르기</button>
            </div>
            {this.loading && <div className='sh-muted'>찾는 중…</div>}
            {!this.loading && this.entries.length === 0 && <div className='sh-muted'>찾은 인스턴스가 없습니다. [폴더 직접 고르기]로 골라 주세요(압축 파일은 파일 → 가져오기).</div>}
            <table className='imp-table'>
                <thead><tr><th /><th>런처</th><th>이름</th><th>게임 버전</th><th>로더</th><th>모드</th><th>마지막 플레이</th></tr></thead>
                <tbody>
                    {this.entries.map(e => <tr key={e.key} className={this.selected.has(e.key) ? 'selected' : ''} onClick={() => this.toggle(e)}>
                        <td><input type='checkbox' checked={this.selected.has(e.key)} readOnly aria-label={`${e.name} 고르기`} /></td>
                        <td><span className={codicon(LAUNCHER_ICON[e.launcher] ?? 'folder')} /> {e.launcherName}</td>
                        <td>{e.name}{e.importedAs && <span className='sh-chip'>불러옴</span>}{e.note && <div className='sh-muted sh-small'>{e.note}</div>}</td>
                        <td onClick={ev => { if (!e.version) { ev.stopPropagation(); } }}>{e.version ?? <input className='theia-input imp-ver' placeholder='예: 26.3' value={this.versions.get(e.key) ?? ''}
                            onChange={ev => { this.versions.set(e.key, ev.target.value.trim()); this.update(); }} />}</td>
                        <td>{LOADER_LABELS[e.loader] ?? e.loader}{e.loaderVersion ? ` ${e.loaderVersion}` : ''}</td>
                        <td>{e.mods}</td>
                        <td>{e.lastPlayed ? e.lastPlayed.replace('T', ' ').slice(0, 16) : '—'}</td>
                    </tr>)}
                </tbody>
            </table>
            <div className='sh-actions'>
                <button className='theia-button' disabled={!this.selected.size || need.length > 0} onClick={() => this.showPreview()}>
                    다음 ({this.selected.size}개 고름)</button>
                {need.length > 0 && <span className='sh-muted'>버전을 알 수 없는 항목은 게임 버전을 넣어 주세요.</span>}
            </div>
            <p className='sh-muted sh-small'>계정·로그인 파일은 읽지도 옮기지도 않습니다. 원본 런처의 파일은 바꾸지 않습니다.</p>
        </>;
    }

    protected renderPreview(): React.ReactNode {
        const p = this.preview!;
        return <>
            <div className='sh-kinds' role='radiogroup' aria-label='불러오기 방식'>
                {([['link', '연결(추천)', '인스턴스 폴더는 원래 자리에 그대로 두고, 여기서 실행·모드 추가·서버 열기를 합니다(용량 없음). 두 런처에서 동시에 켜면 안 됩니다 — 실행 전에 확인합니다. 목록에서 지워도 원래 폴더는 남습니다.'],
                    ['copy', '복사', '통합 작업실 폴더로 mods·config·saves·resourcepacks·shaderpacks·options.txt·servers.dat 등을 복사합니다. 원본은 그대로.']] as const)
                    .map(([m, t, d]) => <label key={m} className={'sh-kind' + (this.mode === m ? ' selected' : '')}>
                        <input type='radio' checked={this.mode === m} onChange={async () => { this.mode = m; await this.showPreview(); }} />
                        <span><b>{t}</b><span className='sh-muted'>{d}</span></span></label>)}
            </div>
            {p.warnings.map((w, i) => <div key={i} className={'sh-note' + (i === 0 && p.mode === 'link' ? ' warn' : '')}>{w}</div>)}
            {p.items.map(it => <section key={it.key} className='sh-card'>
                <div className='sh-card-head'><b className='sh-name'>{it.name}</b><span className='sh-chip'>{it.launcherName}</span>
                    <span className='sh-muted'>{it.version ?? this.versions.get(it.key)} · {LOADER_LABELS[it.loader] ?? it.loader}</span></div>
                {p.mode === 'copy'
                    ? <div className='sh-small'>{it.items.map(x => `${x.name} ${formatBytes(x.bytes)}`).join(' · ') || '옮길 항목 없음'} — 합계 {formatBytes(it.bytes)}</div>
                    : <div className='sh-small sh-mono'>{it.gameDir}</div>}
            </section>)}
            {p.mode === 'copy' && <div className='sh-small'>전체 {formatBytes(p.bytes)}</div>}
            <div className='sh-actions'>
                <button className='theia-button secondary' onClick={() => { this.step = 'list'; this.update(); }}>뒤로</button>
                <button className='theia-button' onClick={() => this.run()}>불러오기</button>
            </div>
        </>;
    }

    protected renderDone(): React.ReactNode {
        const r = this.result!;
        return <>
            <div className='sh-note'>{r.imported.length}개를 불러왔습니다{r.failed.length ? `, ${r.failed.length}개 실패` : ''}. {this.mode === 'link'
                ? '원래 폴더를 그대로 연결했고 이 앱에는 아무것도 설치하지 않았습니다. 각 인스턴스의 게임 폴더(.minecraft) 안에 실행 파일(통합 작업실 실행.cmd)을 만들었고, [실행]하면 그 파일이 원래 런처를 엽니다.'
                : '버전·로더는 필요할 때만 설치했습니다.'}</div>
            {r.imported.map(i => <section key={i.id} className='sh-card'>
                <div className='sh-card-head'><b className='sh-name'>{i.name}</b><span className='sh-muted'>{i.version} · {LOADER_LABELS[i.loader] ?? i.loader}</span></div>
                {i.linkedDir && <div className='sh-small sh-muted'>연결: {i.linkedDir}</div>}
                {i.launchFile && <div className='sh-small sh-muted'>실행 파일: {i.launchFile} — [실행]하면 이 파일이 원래 런처를 엽니다</div>}
                {i.warning && <div className='sh-note warn'>{i.warning}</div>}
                <div className='sh-card-actions'>
                    <button className='theia-button' onClick={() => this.commands.executeCommand(ServerHostCommands.HOST_INSTANCE.id, i.id)}>
                        <span className={codicon('broadcast')} /> 서버로 열기</button>
                    <button className='theia-button secondary' onClick={() => this.commands.executeCommand('studio.instance.launch', i.id)}>
                        <span className={codicon('play')} /> 실행</button>
                </div>
            </section>)}
            {r.failed.map(f => <div key={f.key} className='sh-note error'>{f.name}: {f.error}</div>)}
            <div className='sh-actions'>
                <button className='theia-button secondary' onClick={() => { this.step = 'list'; this.selected.clear(); this.detect(); }}>더 불러오기</button>
            </div>
        </>;
    }
}
