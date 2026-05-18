package com.plaindb.dbeaver.service;

import java.io.IOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

/**
 * Backend-only PlainDB HTTP client.
 *
 * All SQL generation/execution/verification operations are delegated to backend endpoints.
 */
public final class SqlGeneratorClient {
    public interface ProgressListener {
        void onProgress(String stage, String message);
    }

    private final String apiKey;
    private final String provider;
    private final String endpointUrl;
    private final String llmModel;

    public SqlGeneratorClient(String apiKey, String provider, String endpointUrl, String llmModel) {
        this.apiKey = apiKey;
        this.provider = (provider == null || provider.isBlank()) ? "gemini" : provider;
        this.endpointUrl = endpointUrl;
        this.llmModel = (llmModel == null || llmModel.isBlank()) ? "gemini-2.5-flash" : llmModel;
    }

    public static final class DatabaseTargetPayload {
        public String dialect;
        public String database;
        public String username;
        public String password;
        public String host;
        public Integer port;
        public String schema;
        public String connectionString;
    }

    public static final class BackendRunResult {
        public boolean accepted;
        public boolean committed;
        public int attempts;
        public int rowcount;      // from execution.rowcount in the API response
        public String generatedSql;
        public String error;
        public String errorKind;
        public String rollbackId;
        public String rawJson;
    }

    public BackendRunResult runBackend(String request, DatabaseTargetPayload target, boolean dryRun, int maxRetries) throws Exception {
        if (endpointUrl == null || endpointUrl.isBlank()) {
            throw new IllegalArgumentException("Backend URL is required for backend mode.");
        }

        String payload = buildBackendRunRequestJson(request, target, dryRun, maxRetries);
        String response = callBackendApi("/run", "POST", payload);

        BackendRunResult result = new BackendRunResult();
        result.rawJson = response;
        result.accepted = extractJsonBoolean(response, "accepted");
        result.committed = extractJsonBoolean(response, "committed");
        result.attempts = extractJsonInt(response, "attempts", 0);
        result.rowcount = extractJsonInt(response, "rowcount", 0);
        result.generatedSql = valueOrDefault(extractJsonString(response, "generated_sql"), extractJsonString(response, "sql"));
        result.error = extractJsonString(response, "error");
        result.errorKind = extractJsonString(response, "error_kind");
        result.rollbackId = extractJsonString(response, "rollback_id");
        return result;
    }

    public BackendRunResult runBackendStream(
        String request,
        DatabaseTargetPayload target,
        boolean dryRun,
        int maxRetries,
        ProgressListener progressListener
    ) throws Exception {
        if (endpointUrl == null || endpointUrl.isBlank()) {
            throw new IllegalArgumentException("Backend URL is required for backend mode.");
        }

        String payload = buildBackendRunRequestJson(request, target, dryRun, maxRetries);
        String response = callBackendStreamApi("/run/stream", "POST", payload, progressListener);

        BackendRunResult result = new BackendRunResult();
        result.rawJson = response;
        result.accepted = extractJsonBoolean(response, "accepted");
        result.committed = extractJsonBoolean(response, "committed");
        result.attempts = extractJsonInt(response, "attempts", 0);
        result.rowcount = extractJsonInt(response, "rowcount", 0);
        result.generatedSql = valueOrDefault(extractJsonString(response, "generated_sql"), extractJsonString(response, "sql"));
        result.error = extractJsonString(response, "error");
        result.errorKind = extractJsonString(response, "error_kind");
        result.rollbackId = extractJsonString(response, "rollback_id");
        return result;
    }

    public void applyRollback(String rollbackId) throws Exception {
        if (rollbackId == null || rollbackId.isBlank()) {
            throw new IllegalArgumentException("Rollback id is required.");
        }
        if (endpointUrl == null || endpointUrl.isBlank()) {
            throw new IllegalArgumentException("Backend URL is required for rollback.");
        }
        callBackendApi("/rollback/" + URLEncoder.encode(rollbackId, StandardCharsets.UTF_8.name()), "POST", null);
    }

    private String buildBackendRunRequestJson(String request, DatabaseTargetPayload target, boolean dryRun, int maxRetries) {
        String dialect = valueOrDefault(target == null ? null : target.dialect, "sqlite");
        String database = valueOrDefault(target == null ? null : target.database, ":memory:");
        String username = target == null ? null : target.username;
        String password = target == null ? null : target.password;
        String host = target == null ? null : target.host;
        Integer port = target == null ? null : target.port;
        String schema = target == null ? null : target.schema;
        String connectionString = target == null ? null : target.connectionString;

        StringBuilder sb = new StringBuilder();
        sb.append("{");
        sb.append("\"intent_text\":\"").append(escapeJson(valueOrDefault(request, ""))).append("\",");
        sb.append("\"api_key\":\"").append(escapeJson(valueOrDefault(apiKey, ""))).append("\",");
        sb.append("\"provider\":\"").append(escapeJson(provider)).append("\",");
        sb.append("\"model_name\":\"").append(escapeJson(llmModel)).append("\",");
        sb.append("\"dry_run\":").append(dryRun).append(",");
        sb.append("\"max_retries\":").append(Math.max(0, maxRetries)).append(",");
        sb.append("\"database_target\":{");
        sb.append("\"dialect\":\"").append(escapeJson(dialect)).append("\",");
        sb.append("\"database\":\"").append(escapeJson(database)).append("\",");
        appendOptionalString(sb, "username", username);
        appendOptionalString(sb, "password", password);
        appendOptionalString(sb, "host", host);
        appendOptionalNumber(sb, "port", port);
        appendOptionalString(sb, "schema", schema);
        appendOptionalString(sb, "connection_string", connectionString);
        sb.append("\"options\":{}");
        sb.append("}");
        sb.append("}");
        return sb.toString();
    }

    private String callBackendApi(String path, String method, String jsonBody) throws IOException {
        String base = endpointUrl.endsWith("/") ? endpointUrl.substring(0, endpointUrl.length() - 1) : endpointUrl;
        URL url = new URL(base + path);

        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod(method);
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setRequestProperty("Connection", "keep-alive");
        conn.setConnectTimeout(30000);
        conn.setReadTimeout(60000);

        if (jsonBody != null) {
            conn.setDoOutput(true);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(jsonBody.getBytes(StandardCharsets.UTF_8));
                os.flush();
            }
        }

        int responseCode = conn.getResponseCode();
        if (responseCode < 200 || responseCode >= 300) {
            String err = readResponseError(conn);
            throw new IOException("PlainDB backend returned status " + responseCode + ": " + err);
        }

        return readResponse(conn);
    }

    private String callBackendStreamApi(
        String path,
        String method,
        String jsonBody,
        ProgressListener progressListener
    ) throws IOException {
        String base = endpointUrl.endsWith("/") ? endpointUrl.substring(0, endpointUrl.length() - 1) : endpointUrl;
        URL url = new URL(base + path);

        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod(method);
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setRequestProperty("Accept", "application/x-ndjson");
        conn.setRequestProperty("Connection", "keep-alive");
        conn.setConnectTimeout(30000);
        conn.setReadTimeout(120000);

        if (jsonBody != null) {
            conn.setDoOutput(true);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(jsonBody.getBytes(StandardCharsets.UTF_8));
                os.flush();
            }
        }

        int responseCode = conn.getResponseCode();
        if (responseCode < 200 || responseCode >= 300) {
            String err = readResponseError(conn);
            throw new IOException("PlainDB backend returned status " + responseCode + ": " + err);
        }

        String finalLine = null;
        try (java.io.BufferedReader reader = new java.io.BufferedReader(
            new java.io.InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8)
        )) {
            String line;
            while ((line = reader.readLine()) != null) {
                String trimmed = line.trim();
                if (trimmed.isEmpty()) {
                    continue;
                }
                String event = extractJsonString(trimmed, "event");
                if ("progress".equals(event)) {
                    if (progressListener != null) {
                        String stage = valueOrDefault(extractJsonString(trimmed, "stage"), "progress");
                        String message = valueOrDefault(extractJsonString(trimmed, "message"), stage);
                        progressListener.onProgress(stage, message);
                    }
                    continue;
                }
                if ("error".equals(event)) {
                    String error = valueOrDefault(extractJsonString(trimmed, "error"), "Streaming execution failed.");
                    throw new IOException(error);
                }
                if ("final".equals(event)) {
                    finalLine = trimmed;
                }
            }
        }

        if (finalLine == null || finalLine.isBlank()) {
            throw new IOException("Streaming backend did not return a final result.");
        }
        return finalLine;
    }

    private String readResponse(HttpURLConnection conn) throws IOException {
        java.io.BufferedReader reader = new java.io.BufferedReader(
            new java.io.InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8)
        );
        StringBuilder response = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            response.append(line);
        }
        reader.close();
        return response.toString();
    }

    private String readResponseError(HttpURLConnection conn) {
        try {
            java.io.InputStream es = conn.getErrorStream();
            if (es == null) return "";
            java.io.BufferedReader reader = new java.io.BufferedReader(new java.io.InputStreamReader(es, StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line);
            }
            reader.close();
            return sb.toString();
        } catch (Exception e) {
            return "(unable to read error body)";
        }
    }

    private String extractJsonString(String json, String key) {
        if (json == null || key == null) {
            return null;
        }
        String pattern = "\"" + key + "\":\"";
        int start = json.indexOf(pattern);
        if (start < 0) {
            return null;
        }
        start += pattern.length();
        StringBuilder out = new StringBuilder();
        boolean escaped = false;
        for (int i = start; i < json.length(); i++) {
            char ch = json.charAt(i);
            if (escaped) {
                switch (ch) {
                    case 'n': out.append('\n'); break;
                    case 'r': out.append('\r'); break;
                    case 't': out.append('\t'); break;
                    case '"': out.append('"'); break;
                    case '\\': out.append('\\'); break;
                    default: out.append(ch); break;
                }
                escaped = false;
                continue;
            }
            if (ch == '\\') {
                escaped = true;
                continue;
            }
            if (ch == '"') {
                return out.toString();
            }
            out.append(ch);
        }
        return null;
    }

    private boolean extractJsonBoolean(String json, String key) {
        if (json == null || key == null) {
            return false;
        }
        String truePattern = "\"" + key + "\":true";
        String falsePattern = "\"" + key + "\":false";
        if (json.contains(truePattern)) {
            return true;
        }
        if (json.contains(falsePattern)) {
            return false;
        }
        return false;
    }

    private int extractJsonInt(String json, String key, int defaultValue) {
        if (json == null || key == null) {
            return defaultValue;
        }
        String pattern = "\"" + key + "\":";
        int start = json.indexOf(pattern);
        if (start < 0) {
            return defaultValue;
        }
        start += pattern.length();
        int end = start;
        while (end < json.length() && Character.isDigit(json.charAt(end))) {
            end++;
        }
        if (end == start) {
            return defaultValue;
        }
        try {
            return Integer.parseInt(json.substring(start, end));
        } catch (Exception ignored) {
            return defaultValue;
        }
    }

    private void appendOptionalString(StringBuilder sb, String key, String value) {
        sb.append("\"").append(key).append("\":");
        if (value == null || value.isBlank()) {
            sb.append("null,");
            return;
        }
        sb.append("\"").append(escapeJson(value)).append("\",");
    }

    private void appendOptionalNumber(StringBuilder sb, String key, Integer value) {
        sb.append("\"").append(key).append("\":");
        if (value == null) {
            sb.append("null,");
            return;
        }
        sb.append(value).append(',');
    }

    private String valueOrDefault(String value, String defaultValue) {
        if (value == null || value.isBlank()) {
            return defaultValue;
        }
        return value;
    }

    private String escapeJson(String text) {
        if (text == null) {
            return "";
        }
        return text.replace("\\", "\\\\")
                   .replace("\"", "\\\"")
                   .replace("\n", "\\n")
                   .replace("\r", "\\r")
                   .replace("\t", "\\t");
    }
}
