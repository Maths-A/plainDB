package com.plaindb.dbeaver.service;

import java.io.IOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

/**
 * Calls AI APIs (OpenAI, Gemini, local PlainDB service) to generate SQL.
 */
public final class SqlGeneratorClient {
    private final String apiKey;
    private final String apiProvider; // "openai", "plaindb" or "gemini"
    private final String endpointUrl;
    private final String llmModel;

    public SqlGeneratorClient(String apiKey, String apiProvider, String endpointUrl, String llmModel) {
        this.apiKey = apiKey;
        this.apiProvider = apiProvider;
        this.endpointUrl = endpointUrl;
        this.llmModel = (llmModel == null || llmModel.isBlank()) ? "gemini-2.5-flash" : llmModel;
    }

    /**
     * Generate SQL from a natural language request.
     */
    public String generateSql(String request, String databaseType) throws Exception {
        if ("openai".equalsIgnoreCase(apiProvider)) {
            return generateSqlViaOpenAI(request, databaseType);
        } else if ("gemini".equalsIgnoreCase(apiProvider)) {
            return generateSqlViaGemini(request, databaseType);
        } else if ("plaindb".equalsIgnoreCase(apiProvider)) {
            return generateSqlViaPlainDB(request, databaseType);
        }

        throw new IllegalArgumentException("Unknown API provider: " + apiProvider);
    }

    /**
     * Explain database errors in beginner-friendly language.
     */
    public String explainDatabaseError(String databaseType, String sql, String errorMessage) throws Exception {
        if (apiKey == null || apiKey.isBlank()) {
            throw new IllegalArgumentException("API key is required for Gemini explanation");
        }

        String model = llmModel;
        String systemPrompt = "You are a patient SQL tutor for beginners. Explain database errors in very simple language. "
            + "Return only plain text with 1 short sentence explanation and avoid technical jargon. If the error message contains sensitive information, do not include it in the explanation.";

        String userPrompt = "Database type: " + (databaseType == null ? "unknown" : databaseType) + "\n"
            + "SQL:\n" + (sql == null ? "(not available)" : sql) + "\n"
            + "Error:\n" + (errorMessage == null ? "(not available)" : errorMessage) + "\n"
            + "Keep it beginner-friendly and concrete.";

        java.util.List<String> endpoints = new java.util.ArrayList<>();
        endpoints.add("https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent");
        endpoints.add("https://generativelanguage.googleapis.com/v1/models/" + model + ":generateContent");

        IOException lastException = null;
        for (String target : endpoints) {
            boolean useApiKeyQuery = apiKey.startsWith("AIza");
            String urlStr = target + (useApiKeyQuery && !target.contains("?") ? "?key=" + URLEncoder.encode(apiKey, StandardCharsets.UTF_8.name()) : "");

            try {
                URL url = new URL(urlStr);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
                if (!useApiKeyQuery) {
                    conn.setRequestProperty("Authorization", "Bearer " + apiKey);
                }
                conn.setConnectTimeout(15000);
                conn.setReadTimeout(30000);
                conn.setDoOutput(true);

                String jsonRequest = buildGeminiRequestJson(systemPrompt, userPrompt);
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(jsonRequest.getBytes(StandardCharsets.UTF_8));
                    os.flush();
                }

                int responseCode = conn.getResponseCode();
                if (responseCode == 200) {
                    String response = readResponse(conn);
                    String text = extractSqlFromGeminiResponse(response);
                    if (text != null && !text.isBlank()) {
                        return text;
                    }
                    throw new IOException("Gemini explanation response was empty");
                }

                if (responseCode == 404) {
                    continue;
                }

                String errBody = readResponseError(conn);
                throw new IOException("Gemini explanation API returned status " + responseCode + ": " + errBody);
            } catch (IOException e) {
                lastException = e;
            }
        }

        if (lastException != null) {
            throw lastException;
        }
        throw new IOException("Gemini explanation API returned 404 for all attempted endpoints");
    }

    private String generateSqlViaGemini(String request, String databaseType) throws Exception {
        if (apiKey == null || apiKey.isBlank()) {
            throw new IllegalArgumentException("API key is required for Gemini");
        }

        String model = llmModel;
        String systemPrompt = "You are an expert SQL developer. Generate only valid " + databaseType +
            " SQL code. No explanations, just the SQL statement.";
        String userPrompt = "Generate SQL for: " + request;

        java.util.List<String> endpoints = new java.util.ArrayList<>();
        if (endpointUrl != null && !endpointUrl.isBlank()) {
            endpoints.add(endpointUrl.trim());
        }
        endpoints.add("https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent");
        endpoints.add("https://generativelanguage.googleapis.com/v1/models/" + model + ":generateContent");

        IOException lastException = null;
        for (String target : endpoints) {
            boolean useApiKeyQuery = apiKey.startsWith("AIza");
            String urlStr = target + (useApiKeyQuery && !target.contains("?") ? "?key=" + URLEncoder.encode(apiKey, StandardCharsets.UTF_8.name()) : "");

            try {
                URL url = new URL(urlStr);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
                if (!useApiKeyQuery) {
                    conn.setRequestProperty("Authorization", "Bearer " + apiKey);
                }
                conn.setConnectTimeout(30000);
                conn.setReadTimeout(60000);
                conn.setDoOutput(true);

                String jsonRequest = buildGeminiRequestJson(systemPrompt, userPrompt);
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(jsonRequest.getBytes(StandardCharsets.UTF_8));
                    os.flush();
                }

                int responseCode = conn.getResponseCode();
                if (responseCode == 200) {
                    String response = readResponse(conn);
                    String sql = extractSqlFromGeminiResponse(response);
                    if (sql != null && !sql.isBlank()) {
                        return sql;
                    }
                    throw new IOException("Gemini response did not contain SQL text");
                }

                String errBody = readResponseError(conn);
                System.err.println("[PlainDB][Gemini] Request URL: " + urlStr);
                System.err.println("[PlainDB][Gemini] Response code: " + responseCode);
                System.err.println("[PlainDB][Gemini] Error body: " + errBody);

                if (responseCode == 404) {
                    continue;
                }

                throw new IOException("Gemini API returned status " + responseCode + ": " + errBody);
            } catch (IOException e) {
                lastException = e;
                System.err.println("[PlainDB][Gemini] Exception calling " + target + ": " + e.getMessage());
            }
        }

        if (lastException != null) {
            throw lastException;
        }
        throw new IOException("Gemini API returned 404 for all attempted endpoints");
    }

    private String buildGeminiRequestJson(String systemPrompt, String userPrompt) {
        return String.format(
            "{\"systemInstruction\":{\"parts\":[{\"text\":\"%s\"}]},\"contents\":[{\"role\":\"user\",\"parts\":[{\"text\":\"%s\"}]}],\"generationConfig\":{\"temperature\":0.2,\"maxOutputTokens\":1024}}",
            escapeJson(systemPrompt),
            escapeJson(userPrompt)
        );
    }

    private String generateSqlViaOpenAI(String request, String databaseType) throws Exception {
        if (apiKey == null || apiKey.isBlank()) {
            throw new IllegalArgumentException("API key is required for OpenAI");
        }

        String systemPrompt = "You are an expert SQL developer. Generate only valid " + databaseType +
            " SQL code. No explanations, just the SQL statement.";
        String userPrompt = "Generate SQL for: " + request;

        String jsonRequest = String.format(
            "{\"model\":\"gpt-3.5-turbo\",\"messages\":[" +
            "{\"role\":\"system\",\"content\":\"%s\"}," +
            "{\"role\":\"user\",\"content\":\"%s\"}" +
            "],\"temperature\":0.3}",
            escapeJson(systemPrompt),
            escapeJson(userPrompt)
        );

        return callOpenAIAPI(jsonRequest);
    }

    private String generateSqlViaPlainDB(String request, String databaseType) throws Exception {
        String jsonRequest = String.format(
            "{\"prompt\":\"%s\",\"database_type\":\"%s\"}",
            escapeJson(request),
            databaseType
        );

        return callPlainDBAPI(jsonRequest);
    }

    private String callOpenAIAPI(String jsonBody) throws IOException {
        URL url = new URL("https://api.openai.com/v1/chat/completions");
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setRequestProperty("Authorization", "Bearer " + apiKey);
        conn.setConnectTimeout(30000);
        conn.setReadTimeout(60000);
        conn.setDoOutput(true);

        try (OutputStream os = conn.getOutputStream()) {
            os.write(jsonBody.getBytes(StandardCharsets.UTF_8));
            os.flush();
        }

        int responseCode = conn.getResponseCode();
        if (responseCode != 200) {
            String err = readResponseError(conn);
            System.err.println("[PlainDB][OpenAI] Request URL: " + url);
            System.err.println("[PlainDB][OpenAI] Response code: " + responseCode);
            System.err.println("[PlainDB][OpenAI] Error body: " + err);
            throw new IOException("OpenAI API returned status " + responseCode + ": " + err);
        }

        return extractSqlFromOpenAIResponse(readResponse(conn));
    }

    private String callPlainDBAPI(String jsonBody) throws IOException {
        URL url = new URL(endpointUrl + "/api/v1/generate-sql");
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setConnectTimeout(30000);
        conn.setReadTimeout(60000);
        conn.setDoOutput(true);

        try (OutputStream os = conn.getOutputStream()) {
            os.write(jsonBody.getBytes(StandardCharsets.UTF_8));
            os.flush();
        }

        int responseCode = conn.getResponseCode();
        if (responseCode != 200) {
            String err = readResponseError(conn);
            System.err.println("[PlainDB][Local] Request URL: " + url);
            System.err.println("[PlainDB][Local] Response code: " + responseCode);
            System.err.println("[PlainDB][Local] Error body: " + err);
            throw new IOException("PlainDB API returned status " + responseCode + ": " + err);
        }

        return extractSqlFromPlainDBResponse(readResponse(conn));
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

    private String extractSqlFromOpenAIResponse(String jsonResponse) {
        try {
            int contentStart = jsonResponse.indexOf("\"content\":\"");
            if (contentStart == -1) {
                return "-- Error parsing OpenAI response";
            }
            contentStart += 11;
            int contentEnd = jsonResponse.indexOf('"', contentStart);
            String content = jsonResponse.substring(contentStart, contentEnd);
            content = content.replace("\\n", "\n");
            content = content.replace("\\\"", "\"");
            content = content.replace("\\\\", "\\");
            return content;
        } catch (Exception e) {
            return "-- Error extracting SQL: " + e.getMessage();
        }
    }

    private String extractSqlFromGeminiResponse(String jsonResponse) {
        try {
            int cand = jsonResponse.indexOf("\"candidates\"");
            if (cand != -1) {
                int textIdx = jsonResponse.indexOf("\"text\"", cand);
                if (textIdx != -1) {
                    int start = jsonResponse.indexOf(':', textIdx) + 1;
                    int quote = jsonResponse.indexOf('"', start);
                    if (quote != -1) {
                        int end = jsonResponse.indexOf('"', quote + 1);
                        if (end != -1) {
                            String output = jsonResponse.substring(quote + 1, end);
                            output = output.replace("\\n", "\n").replace("\\\"", "\"").replace("\\\\", "\\");
                            return output;
                        }
                    }
                }
            }

            int out = jsonResponse.indexOf("\"text\":\"");
            if (out != -1) {
                int s = out + 8;
                int e = jsonResponse.indexOf('"', s);
                if (e != -1) {
                    String output = jsonResponse.substring(s, e);
                    return output.replace("\\n", "\n").replace("\\\"", "\"").replace("\\\\", "\\");
                }
            }

            return "-- Error: could not parse Gemini response";
        } catch (Exception e) {
            return "-- Error extracting Gemini SQL: " + e.getMessage();
        }
    }

    private String extractSqlFromPlainDBResponse(String jsonResponse) {
        try {
            int sqlStart = jsonResponse.indexOf("\"sql\":\"");
            if (sqlStart == -1) {
                return "-- Error parsing PlainDB response";
            }
            sqlStart += 7;
            int sqlEnd = jsonResponse.indexOf('"', sqlStart);
            String sql = jsonResponse.substring(sqlStart, sqlEnd);
            sql = sql.replace("\\n", "\n");
            sql = sql.replace("\\\"", "\"");
            sql = sql.replace("\\\\", "\\");
            return sql;
        } catch (Exception e) {
            return "-- Error extracting SQL: " + e.getMessage();
        }
    }

    private String escapeJson(String text) {
        return text.replace("\\", "\\\\")
                   .replace("\"", "\\\"")
                   .replace("\n", "\\n")
                   .replace("\r", "\\r")
                   .replace("\t", "\\t");
    }
}