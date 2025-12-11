declare global {
  interface Window {
    OT: typeof import('@opentok/client');
  }
}

export {};