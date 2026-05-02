import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <main className="min-h-screen flex items-center justify-center px-4 py-12">
      <SignIn signUpUrl="/sign-up" />
    </main>
  );
}
