INSERT INTO "users" ("email", "name", "jobTitle", "department", "bio", "updated_at") 
VALUES ('ai-agent@vsm.dev', 'VSM AI Agent', 'Autonomous Scrum Orchestrator', 'AI Engineering', 'I manage your workflow so you can focus on coding.', NOW())
ON CONFLICT ("email") DO UPDATE SET "name" = EXCLUDED.name
RETURNING "id";
