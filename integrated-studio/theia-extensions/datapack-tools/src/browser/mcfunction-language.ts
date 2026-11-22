import * as monaco from '@theia/monaco-editor-core';

export const MCFUNCTION_ID = 'mcfunction';

/** 게임이 꺼져 있을 때도 보이는 기본 문법 색. 게임이 켜지면 CommandCrafter의 의미 토큰이 위에 덧칠된다. */
export function registerMcfunctionLanguage(): void {
    if (!monaco.languages.getLanguages().some(l => l.id === MCFUNCTION_ID)) {
        monaco.languages.register({ id: MCFUNCTION_ID, extensions: ['.mcfunction'], aliases: ['mcfunction', 'Minecraft Function'] });
    }
    monaco.languages.setLanguageConfiguration(MCFUNCTION_ID, {
        comments: { lineComment: '#' },
        brackets: [['[', ']'], ['{', '}'], ['(', ')']],
        autoClosingPairs: [
            { open: '[', close: ']' }, { open: '{', close: '}' }, { open: '(', close: ')' },
            { open: '"', close: '"', notIn: ['string'] },
        ],
    });
    monaco.languages.setMonarchTokensProvider(MCFUNCTION_ID, {
        tokenizer: {
            root: [
                [/^\s*#.*$/, 'comment'],
                [/^\s*\$/, 'keyword'],
                [/^\s*[a-z_]+/, 'keyword'],
                [/\b(run|as|at|if|unless|positioned|rotated|facing|anchored|align|in|on|store|result|success|summon)\b/, 'keyword'],
                [/@[aeprsn](?=\[)/, { token: 'variable', next: '@selector' }],
                [/@[aeprsn]\b/, 'variable'],
                [/#?[a-z0-9_.\-]+:[a-z0-9_./\-]+/, 'string'],
                [/\$\([a-zA-Z0-9_]+\)/, 'variable'],
                [/[~^]-?\d*\.?\d*/, 'number'],
                [/-?\d+(\.\d+)?[bsldfBSLDF]?\b/, 'number'],
                [/"([^"\\]|\\.)*"/, 'string'],
                [/'([^'\\]|\\.)*'/, 'string'],
            ],
            selector: [
                [/\]/, { token: 'variable', next: '@pop' }],
                [/[^\]]+/, 'variable'],
            ],
        },
    } as monaco.languages.IMonarchLanguage);
}

interface CmdNode {
    arg?: string;
    c?: Record<string, CmdNode>;
    r?: string[];
}

export interface CommandsData {
    tree: CmdNode;
    registries: Record<string, string[]>;
}

const REGISTRY_FOR_PARSER: Record<string, string> = {
    'minecraft:item_stack': 'minecraft:item',
    'minecraft:item_predicate': 'minecraft:item',
    'minecraft:block_state': 'minecraft:block',
    'minecraft:block_predicate': 'minecraft:block',
    'minecraft:entity_summon': 'minecraft:entity_type',
    'minecraft:particle': 'minecraft:particle_type',
};

/** 데이터 생성기 commands.json 기반 예비 자동완성 */
export function createFallbackCompletion(getData: () => CommandsData | undefined, isActive: () => boolean): monaco.languages.CompletionItemProvider {
    return {
        triggerCharacters: [' ', ':'],
        provideCompletionItems(model, position) {
            const data = getData();
            if (!data || !isActive()) {
                return { suggestions: [] };
            }
            const line = model.getLineContent(position.lineNumber).slice(0, position.column - 1).replace(/^\s*\$?/, '');
            if (line.startsWith('#')) {
                return { suggestions: [] };
            }
            const words = line.split(/\s+/);
            const current = words.pop() ?? '';
            const resolve = (path: string[]): CmdNode | undefined => {
                let n: CmdNode | undefined = data.tree;
                for (const p of path) { n = n?.c?.[p]; }
                return n;
            };
            let node: CmdNode | undefined = data.tree;
            for (const w of words) {
                const kids: Record<string, CmdNode> | undefined = node?.c;
                if (!kids) { node = undefined; break; }
                const literal = kids[w];
                node = literal && !literal.arg ? literal : Object.values(kids).find(n => n.arg);
                // 리다이렉트(예: execute ... run → 처음, execute as → execute)
                if (node?.r && !node.c) {
                    node = resolve(node.r);
                } else if (node && !node.c && !node.arg && w === 'run') {
                    node = data.tree;
                }
            }
            if (!node?.c) {
                return { suggestions: [] };
            }
            const range = new monaco.Range(position.lineNumber, position.column - current.length, position.lineNumber, position.column);
            const suggestions: monaco.languages.CompletionItem[] = [];
            for (const [name, child] of Object.entries(node.c)) {
                if (!child.arg) {
                    suggestions.push({ label: name, kind: monaco.languages.CompletionItemKind.Keyword, insertText: name, range });
                } else {
                    const reg = REGISTRY_FOR_PARSER[child.arg];
                    if (reg && data.registries[reg] && current.length >= 1) {
                        for (const id of data.registries[reg]) {
                            suggestions.push({
                                label: id, kind: monaco.languages.CompletionItemKind.Value, range,
                                insertText: id, filterText: id.replace(/^minecraft:/, ''),
                            });
                        }
                    } else {
                        suggestions.push({
                            label: `<${name}>`, kind: monaco.languages.CompletionItemKind.Variable, range,
                            insertText: '', detail: child.arg, documentation: '인자 자리',
                        });
                    }
                }
            }
            return { suggestions };
        },
    };
}
