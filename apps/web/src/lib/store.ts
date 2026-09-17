import { create } from "zustand";

type UIState = {
  collapsed: boolean;
  toggle: () => void;
  realtimeConnected: boolean;
  setRealtimeConnected: (connected: boolean) => void;
  selectedConversation: string | null;
  selectConversation: (id: string) => void;
};

export const useUI = create<UIState>((set) => ({
  collapsed: false,
  toggle: () => set((state) => ({ collapsed: !state.collapsed })),
  realtimeConnected: false,
  setRealtimeConnected: (realtimeConnected) => set({ realtimeConnected }),
  selectedConversation: null,
  selectConversation: (id) => set({ selectedConversation: id }),
}));
