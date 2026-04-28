package com.plaindb.dbeaver.request;

public final class PlainDbRequest {
    private final String englishPrompt;
    private final String connectionName;

    public PlainDbRequest(String englishPrompt, String connectionName) {
        this.englishPrompt = englishPrompt;
        this.connectionName = connectionName;
    }

    public String getEnglishPrompt() {
        return englishPrompt;
    }

    public String getConnectionName() {
        return connectionName;
    }
}