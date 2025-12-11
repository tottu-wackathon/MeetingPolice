declare module '@vonage/client-sdk-video' {
  export interface VonageVideoClient {
    initSession(sessionId: string): Session;
    initPublisher(targetElement?: HTMLElement | string, properties?: PublisherOptions): Publisher;
  }

  export interface Session {
    connect(token: string): Promise<void>;
    disconnect(): void;
    publish(publisher: Publisher): Promise<void>;
    unpublish(publisher: Publisher): void;
    subscribe(stream: Stream, targetElement?: HTMLElement | string, properties?: SubscriberOptions): Subscriber;
    unsubscribe(subscriber: Subscriber): void;
    on(event: string, handler: (...args: any[]) => void): void;
    off(event: string, handler?: (...args: any[]) => void): void;
    connection?: Connection;
    streams: Map<string, Stream>;
  }

  export interface Publisher {
    publishAudio(enabled: boolean): void;
    publishVideo(enabled: boolean): void;
    destroy(): void;
    on(event: string, handler: (...args: any[]) => void): void;
    off(event: string, handler?: (...args: any[]) => void): void;
    element?: HTMLElement;
    stream?: Stream;
  }

  export interface Subscriber {
    subscribeToAudio(enabled: boolean): void;
    subscribeToVideo(enabled: boolean): void;
    destroy(): void;
    on(event: string, handler: (...args: any[]) => void): void;
    off(event: string, handler?: (...args: any[]) => void): void;
    element?: HTMLElement;
    stream: Stream;
  }

  export interface Stream {
    streamId: string;
    name?: string;
    hasAudio: boolean;
    hasVideo: boolean;
    connection: Connection;
    creationTime: number;
  }

  export interface Connection {
    connectionId: string;
    creationTime: number;
    data?: string;
  }

  export interface PublisherOptions {
    audioSource?: boolean | string;
    videoSource?: boolean | string;
    publishAudio?: boolean;
    publishVideo?: boolean;
    resolution?: string;
    frameRate?: number;
    mirror?: boolean;
    name?: string;
  }

  export interface SubscriberOptions {
    subscribeToAudio?: boolean;
    subscribeToVideo?: boolean;
    preferredResolution?: string;
    preferredFrameRate?: number;
  }

  export interface VideoError {
    code: number;
    message: string;
  }

  export default function createVonageVideoClient(apiKey: string): VonageVideoClient;
}