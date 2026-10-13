import { AppShell } from "@/components/shell";
import { Protected } from "@/components/providers";
export default function ProtectedLayout({ children }: { children: React.ReactNode }) { return <Protected><AppShell>{children}</AppShell></Protected>; }
