import * as React from '@theia/core/shared/react';
import { ReactDialog } from '@theia/core/lib/browser/dialogs/react-dialog';
import { Instance } from '../common/index.js';
import { InstanceManager } from './instance-manager.js';
import { CurseForgeKeyForm, Platform, ProjectBrowser, ProjectHit, ProjectVersion, VersionList } from './project-browser.js';

/** 인스턴스에 Modrinth·CurseForge 모드 추가 (필수 의존 모드 포함). 창을 닫지 않고 여러 개 넣을 수 있다. */
export class AddModsDialog extends ReactDialog<void> {
    protected platform: Platform = 'modrinth';
    protected picked: ProjectHit | undefined;
    protected version: ProjectVersion | undefined;
    protected busy = false;
    protected log: { text: string; level: 'ok' | 'warn' | 'error' }[] = [];
    protected cfHasKey: boolean | undefined;

    constructor(protected readonly manager: InstanceManager, protected readonly instance: Instance,
        protected readonly openUrl: (url: string) => void) {
        super({ title: `모드 추가 — ${instance.name} (Java ${instance.version} · Fabric)`, maxWidth: 1100 });
        this.addClass('studio-newinst-dialog');
        this.addClass('studio-addmods-dialog');
        this.appendCloseButton('닫기');
        this.manager.call<{ hasKey: boolean }>('cf_key_status').then(s => { this.cfHasKey = s.hasKey; this.update(); })
            .catch(() => { this.cfHasKey = false; this.update(); });
    }

    get value(): void { return undefined; }

    protected async add(): Promise<void> {
        if (!this.picked || this.busy) { return; }
        this.busy = true;
        this.update();
        const name = this.picked.title;
        try {
            const res = this.platform === 'modrinth'
                ? await this.manager.call<{ added: string[] }>('modrinth_add_mod', { id: this.instance.id, project: this.picked.id, version_id: this.version?.id ?? null })
                : await this.manager.call<{ added: string[]; manual: string[] }>('cf_add_mod', { id: this.instance.id, mod_id: this.picked.id, file_id: this.version?.id ?? null });
            this.log.unshift({ text: `${name}: ${res.added.length ? res.added.join(', ') + ' 추가' : '추가된 파일 없음'}`, level: 'ok' });
            for (const m of (res as { manual?: string[] }).manual ?? []) {
                this.log.unshift({ text: `직접 받아 mods/에 넣어야 함: ${m}`, level: 'warn' });
            }
            this.manager.log(this.instance.id, `모드 추가: ${res.added.join(', ')}`, 'info', 'studio');
        } catch (e) {
            this.log.unshift({ text: `${name}: ${e instanceof Error ? e.message : e}`, level: 'error' });
        } finally {
            this.busy = false;
            this.update();
        }
    }

    protected render(): React.ReactNode {
        const tab = (p: Platform, label: string) => <button className={'ni-source' + (this.platform === p ? ' active' : '')}
            onClick={() => { this.platform = p; this.picked = undefined; this.version = undefined; this.update(); }}>{label}</button>;
        const needKey = this.platform === 'curseforge' && this.cfHasKey === false;
        return <div className='studio-newinst'>
            <div className='ni-body'>
                <nav className='ni-sources' aria-label='어디서'>
                    {tab('modrinth', 'Modrinth')}
                    {tab('curseforge', 'CurseForge')}
                    <p className='ni-hint'>이 인스턴스의 게임 버전·로더에 맞는 모드만 보여 줍니다. 필수 의존 모드도 함께 넣습니다.</p>
                    {this.instance.ccEnabled && <p className='ni-hint'>바뀐 모드는 게임을 다시 시작하면 적용됩니다.</p>}
                </nav>
                <div className='ni-main'>
                    {needKey
                        ? <CurseForgeKeyForm manager={this.manager} openUrl={this.openUrl} onSaved={() => { this.cfHasKey = true; this.update(); }} />
                        : <section className='ni-platform'>
                            <ProjectBrowser key={this.platform} manager={this.manager} platform={this.platform} kind='mod'
                                gameVersion={this.instance.version} loader={this.instance.loader} picked={this.picked}
                                onPick={h => { if (h?.id !== this.picked?.id) { this.picked = h; this.version = undefined; this.update(); } }} />
                            <div className='ni-platform-versions ni-addmods-bottom'>
                                <div className='ni-addmods-versions'>
                                    <div className='ni-subtitle'>{this.picked ? `${this.picked.title} 버전` : '버전'}</div>
                                    {this.picked
                                        ? <VersionList manager={this.manager} platform={this.platform} projectId={this.picked.id}
                                            gameVersion={this.instance.version} loader={this.instance.loader} value={this.version?.id}
                                            onPick={v => { this.version = v; this.update(); }} />
                                        : <div className='ni-empty'>위에서 모드를 고르세요.</div>}
                                </div>
                                <div className='ni-addmods-side'>
                                    <button className='theia-button' disabled={!this.picked || !this.version || this.busy} onClick={() => this.add()}>
                                        {this.busy ? '넣는 중…' : '이 인스턴스에 추가'}
                                    </button>
                                    <div className='ni-addmods-log' role='log'>
                                        {this.log.map((l, i) => <div key={i} className={'lv-' + l.level}>{l.text}</div>)}
                                    </div>
                                </div>
                            </div>
                        </section>}
                </div>
            </div>
        </div>;
    }
}
