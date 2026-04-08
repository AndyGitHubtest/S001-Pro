import { LucideIcon } from 'lucide-react'

interface SummaryCardProps {
  title: string
  value: string
  change: string
  isPositive: boolean
  icon: LucideIcon
}

export default function SummaryCard({ title, value, change, isPositive, icon: Icon }: SummaryCardProps) {
  return (
    <div className="bg-bg-secondary rounded-xl border border-border p-6 hover:border-info/50 transition-colors">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-text-secondary mb-1">{title}</p>
          <p className="text-2xl font-mono font-bold text-text-primary">{value}</p>
          <p className={`text-sm mt-2 ${isPositive ? 'text-up' : 'text-down'}`}>
            {change}
          </p>
        </div>
        <div className="p-3 bg-bg-tertiary rounded-lg">
          <Icon className={`w-6 h-6 ${isPositive ? 'text-up' : 'text-down'}`} />
        </div>
      </div>
    </div>
  )
}
