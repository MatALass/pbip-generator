// Usage: dotnet run --project tools/tmdl-check -- <SemanticModel/definition folder>...
// Exit code 1 if any folder does not load as a TOM database.
using Microsoft.AnalysisServices.Tabular;

if (args.Length == 0)
{
    Console.Error.WriteLine("usage: tmdl-check <SemanticModel definition folder>...");
    return 2;
}

var failures = 0;
foreach (var folder in args)
{
    try
    {
        var database = TmdlSerializer.DeserializeDatabaseFromFolder(folder);
        var model = database.Model;
        var measures = model.Tables.Sum(t => t.Measures.Count);
        Console.WriteLine(
            $"OK   {folder}: {model.Tables.Count} tables, {measures} measures, " +
            $"{model.Relationships.Count} relationships, culture {model.Culture}");
    }
    catch (Exception ex)
    {
        failures++;
        Console.WriteLine($"FAIL {folder}: {ex.GetType().Name}: {ex.Message}");
        for (var inner = ex.InnerException; inner is not null; inner = inner.InnerException)
        {
            Console.WriteLine($"     caused by {inner.GetType().Name}: {inner.Message}");
        }
    }
}
return failures == 0 ? 0 : 1;
