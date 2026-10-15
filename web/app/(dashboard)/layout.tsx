import { SystemHeader } from "@/components/header/SystemHeader";
import { TabBar } from "@/components/nav/TabBar";
import { loadHeaderData } from "@/lib/header-data";

// The header reads live API data on every request; force dynamic so the production build
// never fetches the API (and therefore never fails when the API is down).
export const dynamic = "force-dynamic";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const data = await loadHeaderData();

  return (
    <div className="min-h-[100dvh]">
      <SystemHeader data={data} />
      <main className="mx-auto max-w-[var(--content-max)] px-4 py-6 lg:px-6">
        <div className="mb-6 max-w-md">
          <TabBar />
        </div>
        {children}
      </main>
    </div>
  );
}
