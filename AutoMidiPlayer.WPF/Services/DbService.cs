using System;
using System.Threading;
using System.Threading.Tasks;
using AutoMidiPlayer.Data;
using StyletIoC;

namespace AutoMidiPlayer.WPF.Services;

public interface IDbService
{
    Task ExecuteLockedAsync(Func<PlayerContext, Task> dbOperation);
    Task<T> ExecuteLockedAsync<T>(Func<PlayerContext, Task<T>> dbOperation);
}

public class DbService : IDbService
{
    private readonly SemaphoreSlim _lock = new(1, 1);
    private readonly IContainer _ioc;

    public DbService(IContainer ioc)
    {
        _ioc = ioc;
    }

    public async Task ExecuteLockedAsync(Func<PlayerContext, Task> dbOperation)
    {
        await _lock.WaitAsync();
        try
        {
            await using var db = _ioc.Get<PlayerContext>();
            await dbOperation(db);
        }
        finally
        {
            _lock.Release();
        }
    }

    public async Task<T> ExecuteLockedAsync<T>(Func<PlayerContext, Task<T>> dbOperation)
    {
        await _lock.WaitAsync();
        try
        {
            await using var db = _ioc.Get<PlayerContext>();
            return await dbOperation(db);
        }
        finally
        {
            _lock.Release();
        }
    }
}
