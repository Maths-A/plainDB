package com.plaindb.dbeaver.service;

public final class PlainDbSqlRedactor {
    public String redact(String internalSql) {
        if (internalSql == null || internalSql.isBlank()) {
            return "[hidden]";
        }
        return "[hidden]";
    }
}
