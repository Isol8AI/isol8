interface Isol8Desktop {
  isDesktop: boolean;
  sendAuthToken: (jwt: string) => void;
  onNodeStatus: (callback: (status: string) => void) => () => void;
}

interface Window {
  isol8?: Isol8Desktop;
}
