import { CommonModule } from '@angular/common';
import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../../../core/services/api.service';
import { WorkspaceService } from '../../../../core/services/workspace.service';
import { ToastService } from '../../../../core/services/toast.service';
import { ChatDisplayMessage } from '../../../../core/models/api.models';

@Component({
  selector: 'app-chat-drawer',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './chat-drawer.component.html',
})
export class ChatDrawerComponent {
  open = signal(false);
  input = '';
  messages = signal<ChatDisplayMessage[]>([
    {
      role: 'assistant',
      text: 'Hi! I call the OpenAI-compatible LLM API configured in Settings › LLM API. ' +
        'Parse your sources and target, then tell me things like "map orderId to orderNumber" or ' +
        '"uppercase the customer name field" — I will propose changes here for you to apply.',
    },
  ]);

  constructor(
    public workspace: WorkspaceService,
    private api: ApiService,
    private toast: ToastService,
  ) {}

  toggle(): void {
    this.open.set(!this.open());
  }

  send(): void {
    const text = this.input.trim();
    if (!text) return;
    this.input = '';
    this.messages.update((m) => [...m, { role: 'user', text }]);
    this.open.set(true);
    const thinkingIdx = this.messages().length;
    this.messages.update((m) => [...m, { role: 'assistant', text: '…thinking' }]);

    this.api.chat(this.workspace.toWorkspace(), text, this.workspace.llm()).subscribe({
      next: (res) => {
        this.messages.update((m) => {
          const copy = [...m];
          copy[thinkingIdx] = { role: 'assistant', text: res.message, actions: res.actions };
          return copy;
        });
      },
      error: (err) => {
        this.messages.update((m) => {
          const copy = [...m];
          copy[thinkingIdx] = { role: 'assistant', text: `Could not process that: ${err.error?.detail ?? err.message}` };
          return copy;
        });
      },
    });
  }

  apply(index: number): void {
    const msg = this.messages()[index];
    if (!msg.actions) return;
    msg.actions.forEach((a) => {
      if (a.op === 'remove') {
        this.workspace.mappings.update((list) => list.filter((m) => m.target !== a.target));
      } else {
        const existing = this.workspace.mappings().find((m) => m.target === a.target);
        if (existing) {
          const inputs = [...existing.inputs];
          a.inputs.forEach((i) => {
            if (!inputs.some((x) => x.source_id === i.source_id && x.path === i.path)) inputs.push(i);
          });
          this.workspace.updateMapping(existing.id, {
            inputs, transform: a.transform || existing.transform, origin: 'ai',
          });
        } else {
          this.workspace.mappings.update((list) => [
            ...list,
            { id: `ai${Date.now()}${Math.random()}`, target: a.target, inputs: a.inputs, transform: a.transform, for_each: false, origin: 'ai' },
          ]);
        }
      }
    });
    this.messages.update((m) => {
      const copy = [...m];
      copy[index] = { ...copy[index], applied: true };
      return copy;
    });
    this.toast.show('Chat changes applied.');
  }

  discard(index: number): void {
    this.messages.update((m) => {
      const copy = [...m];
      copy[index] = { ...copy[index], actions: [] };
      return copy;
    });
  }

  formatInputs(inputs: { source_id: string; path: string }[]): string {
    return inputs.map((i) => `${i.source_id}.${i.path}`).join(', ');
  }
}
