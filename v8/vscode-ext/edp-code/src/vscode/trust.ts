// Restricted Mode (qa report-689ceb50f0 fail 10): the extension declares limited support for untrusted workspaces so the
// Heronry Chat view shows on first open. Everything that runs a program in the folder is git (a repo's own config can name
// hooks, a pager or a filesystem monitor), so those three paths ask here first; the board chat itself runs no workspace code.
import * as vscode from 'vscode';

export const RESTRICTED = 'Restricted Mode: trust this folder to use git features here.';

/** True unless the person has not trusted this folder (an environment without the flag counts as trusted). */
export const trusted = (): boolean => (vscode.workspace as { isTrusted?: boolean } | undefined)?.isTrusted !== false;

/** Throws the Restricted Mode text before a git process is started in an untrusted folder. */
export function requireTrust(): void { if (!trusted()) throw new Error(RESTRICTED); }
