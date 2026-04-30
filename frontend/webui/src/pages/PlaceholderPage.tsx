interface Props {
  title: string;
  description?: string;
}

export default function PlaceholderPage({ title, description }: Props) {
  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div className="max-w-md rounded-xl border border-[var(--border)] bg-[var(--panel)] p-6 text-center shadow-lg">
        <div className="text-lg font-semibold text-[var(--text)]">{title}</div>
        {description && (
          <div className="mt-2 text-sm text-[var(--text-dim)]">{description}</div>
        )}
      </div>
    </div>
  );
}
