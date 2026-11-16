import { AppShell } from "@/components/shell";
import { Protected, PlacoProvider } from "@/components/providers";

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  return (
    <Protected>
      <PlacoProvider>
        <AppShell>{children}</AppShell>
      </PlacoProvider>
    </Protected>
  );
}
