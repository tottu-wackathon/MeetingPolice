declare module '@vonage/client-sdk-video' {
  export interface Session {
    connect(token: string, callback?: (error?: OTError) => void): void;
    disconnect(): void;
    publish(publisher: Publisher, callback?: (error?: OTError) => void): void;
    unpublish(publisher: Publisher): void;
    subscribe(
      stream: Stream,
      targetElement?: HTMLElement | string,
      properties?: SubscriberProperties,
      callback?: (error?: OTError, subscriber?: Subscriber) => void
    ): Subscriber;
    unsubscribe(subscriber: Subscriber): void;
    on(type: string, handler: (...args: any[]) => void): void;
    off(type: string, handler?: (...args: any[]) => void): void;
    connection?: Connection;
  }

  export interface Publisher {
    publishAudio(value: boolean): void;
    publishVideo(value: boolean): void;
    on(type: string, handler: (...args: any[]) => void): void;
    off(type: string, handler?: (...args: any[]) => void): void;
  }

  export interface Subscriber {
    on(type: string, handler: (...args: any[]) => void): void;
    off(type: string, handler?: (...args: any[]) => void): void;
  }

  export interface Stream {
    streamId: string;
    name?: string;
    hasAudio: boolean;
    hasVideo: boolean;
    connection: Connection;
  }

  export interface Connection {
    connectionId: string;
  }

  export interface OTError {
    code: number;
    message: string;
  }

  export interface PublisherProperties {
    insertMode?: 'replace' | 'append' | 'before' | 'after';
    width?: string | number;
    height?: string | number;
    publishAudio?: boolean;
    publishVideo?: boolean;
    mirror?: boolean;
    name?: string;
    videoSource?: 'camera' | 'screen';
    style?: {
      buttonDisplayMode?: 'auto' | 'off' | 'on';
      nameDisplayMode?: 'auto' | 'off' | 'on';
    };
    resolution?: string;
    frameRate?: number;
  }

  export interface SubscriberProperties {
    insertMode?: 'replace' | 'append' | 'before' | 'after';
    width?: string | number;
    height?: string | number;
    style?: {
      buttonDisplayMode?: 'auto' | 'off' | 'on';
      nameDisplayMode?: 'auto' | 'off' | 'on';
    };
    preferredResolution?: { width: number; height: number };
    preferredFrameRate?: number;
  }

  export function initSession(apiKey: string, sessionId: string): Session;
  export function initPublisher(
    targetElement?: HTMLElement | string,
    properties?: PublisherProperties,
    callback?: (error?: OTError) => void
  ): Publisher;
}