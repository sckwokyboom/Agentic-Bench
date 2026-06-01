// Human label for a verify command's build system (frontend-derived, post-run).
export function buildSystemLabel(command: string | null | undefined): string {
  if (!command) return "—";
  const first = command.split(" ")[0] ?? "";
  if (first === "mvn" || first === "./mvnw") return "Maven";
  if (first === "gradle" || first === "./gradlew") return "Gradle";
  if (first === "pytest") return "pytest";
  return "custom";
}
