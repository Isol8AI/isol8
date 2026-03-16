import Link from 'next/link';

export function Navbar() {
  return (
    <nav className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 py-4 border-b border-white/10 bg-black/50 backdrop-blur-md">
      <div className="flex items-center gap-2">
        <Link href="/" className="text-xl font-bold tracking-tight text-white font-host">
          isol8
        </Link>
      </div>

      <div className="hidden md:flex items-center gap-8 text-sm font-medium text-white/70">
        <Link href="#features" className="hover:text-white transition-colors">
          Features
        </Link>
        <Link href="#pricing" className="hover:text-white transition-colors">
          Pricing
        </Link>
        <Link href="#faq" className="hover:text-white transition-colors">
          FAQ
        </Link>
      </div>

      <div className="flex items-center gap-4">
        <Link 
          href="/sign-in" 
          className="text-sm font-medium text-white/70 hover:text-white transition-colors hidden sm:block"
        >
          Log in
        </Link>
        <Link
          href="/chat"
          className="px-4 py-2 text-sm font-medium text-black bg-white rounded-full hover:bg-white/90 transition-colors"
        >
          Get Started
        </Link>
      </div>
    </nav>
  );
}
