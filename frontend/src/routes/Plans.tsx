import { useQuery } from "@tanstack/react-query";
import { Crown, Sparkles, Zap } from "lucide-react";

import { PageHeader } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api } from "@/lib/api";
import type { OrgPlan, PlanInfo } from "@/lib/types";

const PLAN_META: Record<OrgPlan, { label: string; icon: typeof Sparkles; description: string }> = {
  free: { label: "Free", icon: Sparkles, description: "For trying On-Call Sync out." },
  starter: { label: "Starter", icon: Zap, description: "For a growing on-call program." },
  premium: { label: "Premium", icon: Crown, description: "For running on-call across many teams." },
};

export default function Plans() {
  const plan = useQuery({
    queryKey: ["plan"],
    queryFn: () => api.get<PlanInfo>("/org/plan"),
  });

  return (
    <div className="space-y-8">
      <PageHeader
        title="Plans"
        description="Choose how many sync rules your organization can run at once."
      />

      {plan.data && (
        <p className="text-sm text-muted-foreground">
          Using <span className="font-medium text-foreground">{plan.data.rule_count}</span> of{" "}
          <span className="font-medium text-foreground">{plan.data.rule_limit}</span> sync rules
          on the {PLAN_META[plan.data.plan].label} plan.
        </p>
      )}

      <div className="grid gap-6 sm:grid-cols-3">
        {plan.data?.tiers.map((tier) => {
          const meta = PLAN_META[tier.plan];
          const isCurrent = plan.data?.plan === tier.plan;
          return (
            <Card
              key={tier.plan}
              className={isCurrent ? "border-primary shadow-sm" : "border-border/70"}
            >
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <meta.icon className="size-4.5" />
                  </div>
                  {isCurrent && <Badge>Current plan</Badge>}
                </div>
                <CardTitle className="mt-3">{meta.label}</CardTitle>
                <CardDescription>{meta.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-foreground">
                  Up to <span className="font-semibold">{tier.rule_limit}</span> sync rules
                </p>
              </CardContent>
              {!isCurrent && (
                <CardFooter>
                  <Button variant="outline" className="w-full" disabled>
                    Coming soon
                  </Button>
                </CardFooter>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
