"use client";
import { useEffect } from "react";
import { useChatGPTOAuth } from "@/hooks/useChatGPTOAuth";

type Props = {
  onComplete: () => void;
};

export function ChatGPTOAuthStep({ onComplete }: Props) {
  const { state, start } = useChatGPTOAuth();

  useEffect(() => {
    if (state.status === "completed") onComplete();
  }, [state, onComplete]);

  if (state.status === "idle") {
    return (
      <div className="flex flex-col items-center gap-4 py-8">
        <h3 className="text-xl font-semibold">Sign in with ChatGPT</h3>
        <p className="text-sm text-muted-foreground text-center max-w-md">
          Use your existing ChatGPT Plus/Pro subscription for inference. No
          keys to copy.
        </p>
        <button
          onClick={start}
          className="rounded-md bg-primary px-6 py-3 text-primary-foreground font-medium hover:bg-primary/90"
        >
          Connect ChatGPT
        </button>
      </div>
    );
  }

  if (state.status === "pending") {
    return (
      <div className="flex flex-col items-center gap-4 py-8 max-w-md">
        <h3 className="text-xl font-semibold">Almost there</h3>
        <ol className="text-sm space-y-3 list-decimal list-inside">
          <li>
            Open{" "}
            <a
              href={state.verificationUri}
              target="_blank"
              rel="noreferrer"
              className="text-primary underline"
            >
              {state.verificationUri}
            </a>{" "}
            and sign in to your ChatGPT account.
          </li>
          <li>
            Enter this code:
            <div className="mt-2">
              <code className="bg-muted px-3 py-2 rounded font-mono text-lg tracking-widest">
                {state.userCode}
              </code>
            </div>
          </li>
        </ol>
        <p className="text-xs text-muted-foreground">
          Waiting for you to complete sign-in&hellip;
        </p>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col items-center gap-4 py-8">
        <p className="text-destructive">
          Connection failed: {state.message}
        </p>
        <button
          onClick={start}
          className="rounded-md bg-secondary px-4 py-2 text-sm"
        >
          Try again
        </button>
      </div>
    );
  }

  // status === "completed" — useEffect already called onComplete; show
  // a brief checkmark while the parent advances.
  return (
    <div className="flex items-center justify-center py-8 text-primary">
      &#10003; Connected
    </div>
  );
}
