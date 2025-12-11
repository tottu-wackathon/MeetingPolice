declare module '@vonage/client-sdk-video' {
  export function initSession(apiKey: string, sessionId: string): any;
  export function initPublisher(targetElement?: HTMLElement | string, properties?: any): any;
  
  export interface Session {
    connect(token: string, callback?: (error?: any) => void): void;
    disconnect(): void;
    publish(publisher: any, callback?: (error?: any) => void): void;
    unpublish(publisher: any): void;
    subscribe(stream: any, targetElement?: HTMLElement | string, properties?: any, callback?: (error?: any, subscriber?: any) => void): any;
    unsubscribe(subscriber: any): void;
    on(event: string, handler: (...args: any[]) => void): void;
    off(event: string, handler?: (...args: any[]) => void): void;
    connection?: any;
  }

  export interface Publisher {
    publishAudio(enabled: boolean): void;
    publishVideo(enabled: boolean): void;
    on(event: string, handler: (...args: any[]) => void): void;
    off(event: string, handler?: (...args: any[]) => void): void;
    element?: HTMLElement;
  }

  export interface Subscriber {
    on(event: string, handler: (...args: any[]) => void): void;
    off(event: string, handler?: (...args: any[]) => void): void;
    element?: HTMLElement;
    stream: any;
  }

  export interface Stream {
    streamId: string;
    name?: string;
    hasAudio: boolean;
    hasVideo: boolean;
    connection: any;
  }
}