import Link from "next/link";

export function Footer() {
  return (
    <footer className="py-12 px-6 border-t border-white/10 bg-black">
      <div className="max-w-6xl mx-auto flex flex-col md:flex-row justify-between items-center gap-8">
        <div className="text-white font-host font-bold text-xl">
          isol8
        </div>
        
        <div className="flex gap-8 text-sm text-white/60 font-dm">
          <Link href="#" className="hover:text-white transition-colors">Privacy Policy</Link>
          <Link href="#" className="hover:text-white transition-colors">Terms of Service</Link>
          <Link href="#" className="hover:text-white transition-colors">Twitter</Link>
        </div>

        <div className="text-xs text-white/40 font-dm">
          © {new Date().getFullYear()} isol8 Inc. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
