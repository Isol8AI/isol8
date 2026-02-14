/**
 * Isol8 endpoint mapping — replaces the Convex-generated api.js
 *
 * Each entry maps to a REST endpoint on the Isol8 backend.
 * _type indicates whether the frontend calls it as a query (GET) or
 * mutation (POST).
 *
 * Unknown property accesses return a nested Proxy stub so that backend-only
 * code (convex/agent/, convex/engine/, etc.) type-checks without errors.
 */

function createStubProxy(base) {
  return new Proxy(base || {}, {
    get(target, prop) {
      if (prop in target) return target[prop];
      // Return a nested proxy for any unknown namespace
      return createStubProxy({ _type: 'stub', endpoint: `/stub/${String(prop)}` });
    },
  });
}

const endpoints = {
  world: {
    worldState: { _type: 'query', endpoint: '/town/state' },
    defaultWorldStatus: { _type: 'query', endpoint: '/town/status' },
    gameDescriptions: { _type: 'query', endpoint: '/town/descriptions' },
    userStatus: { _type: 'query', endpoint: '/town/user-status' },
    heartbeatWorld: { _type: 'mutation', endpoint: '/town/heartbeat' },
    joinWorld: { _type: 'mutation', endpoint: '/town/join' },
    leaveWorld: { _type: 'mutation', endpoint: '/town/leave' },
    sendWorldInput: { _type: 'mutation', endpoint: '/town/input' },
    previousConversation: { _type: 'query', endpoint: '/town/previous-conversation' },
  },
  messages: {
    listMessages: { _type: 'query', endpoint: '/town/messages' },
    writeMessage: { _type: 'mutation', endpoint: '/town/message' },
  },
  aiTown: {
    main: {
      sendInput: { _type: 'mutation', endpoint: '/town/send-input' },
      inputStatus: { _type: 'query', endpoint: '/town/input-status' },
    },
  },
  music: {
    getBackgroundMusic: { _type: 'query', endpoint: '/town/music' },
  },
  testing: {
    stopAllowed: { _type: 'query', endpoint: '/town/testing/stop-allowed' },
    stop: { _type: 'mutation', endpoint: '/town/testing/stop' },
    resume: { _type: 'mutation', endpoint: '/town/testing/resume' },
  },
};

export const api = createStubProxy(endpoints);
export const internal = createStubProxy(endpoints);
