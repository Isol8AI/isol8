/**
 * Isol8 endpoint mapping types — replaces the Convex-generated api.d.ts
 */

export interface FunctionRef {
  _type: 'query' | 'mutation';
  endpoint: string;
}

export declare const api: {
  world: {
    worldState: FunctionRef;
    defaultWorldStatus: FunctionRef;
    gameDescriptions: FunctionRef;
    userStatus: FunctionRef;
    heartbeatWorld: FunctionRef;
    joinWorld: FunctionRef;
    leaveWorld: FunctionRef;
    sendWorldInput: FunctionRef;
    previousConversation: FunctionRef;
  };
  messages: {
    listMessages: FunctionRef;
    writeMessage: FunctionRef;
  };
  aiTown: {
    main: {
      sendInput: FunctionRef;
      inputStatus: FunctionRef;
    };
  };
  music: {
    getBackgroundMusic: FunctionRef;
  };
  testing: {
    stopAllowed: FunctionRef;
    stop: FunctionRef;
    resume: FunctionRef;
  };
};

export declare const internal: typeof api;
