import Link from "next/link";

export function Footer() {
  return (
    <footer className="landing-footer">
      <div className="footer-inner">
        <span className="footer-logo">ISOL8</span>
        <div className="footer-links">
          <Link href="#">Privacy Policy</Link>
          <Link href="#">Terms of Service</Link>
          <Link href="#">Twitter</Link>
        </div>
        <span className="footer-copy">
          © {new Date().getFullYear()} isol8 Inc. All rights reserved.
        </span>
      </div>
    </footer>
  );
}
