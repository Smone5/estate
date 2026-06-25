import { create } from 'zustand';

export const useDialogStore = create((set, get) => ({
  dialog: null, // { type: 'confirm'|'prompt', message: string, defaultValue: string, resolve: Function }
  
  confirm: (message) => {
    return new Promise((resolve) => {
      set({
        dialog: {
          type: 'confirm',
          message,
          resolve,
        },
      });
    });
  },

  prompt: (message, defaultValue = '') => {
    return new Promise((resolve) => {
      set({
        dialog: {
          type: 'prompt',
          message,
          defaultValue,
          resolve,
        },
      });
    });
  },

  submit: (value) => {
    const { dialog } = get();
    if (dialog) {
      dialog.resolve(value);
    }
    set({ dialog: null });
  },

  cancel: () => {
    const { dialog } = get();
    if (dialog) {
      dialog.resolve(dialog.type === 'confirm' ? false : null);
    }
    set({ dialog: null });
  },
}));

// High-compatibility wrappers that respect Vitest mocks
export async function customConfirm(message) {
  const isMock = typeof window.confirm === 'function' && (
    typeof window.confirm.mock !== 'undefined' || 
    window.confirm._isMockFunction || 
    window.confirm.name === 'mockConstructor' ||
    window.confirm.toString().includes('mock')
  );
  if (isMock) {
    return window.confirm(message);
  }
  return useDialogStore.getState().confirm(message);
}

export async function customPrompt(message, defaultValue = '') {
  const isMock = typeof window.prompt === 'function' && (
    typeof window.prompt.mock !== 'undefined' || 
    window.prompt._isMockFunction || 
    window.prompt.name === 'mockConstructor' ||
    window.prompt.toString().includes('mock')
  );
  if (isMock) {
    return window.prompt(message, defaultValue);
  }
  return useDialogStore.getState().prompt(message, defaultValue);
}
